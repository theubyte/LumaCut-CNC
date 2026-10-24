"""LumaCut: authenticated LAN build dashboard with HMI flashing packages."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
from statistics import median
import base64, hashlib, hmac, json, os, re, secrets, shutil, signal, subprocess, threading, zipfile
from flask import Flask, Response, request, abort, jsonify, send_from_directory, send_file
from flash_bundle import build_flash_package, flash_manifest, IMAGE_NAME

ROOT=Path(os.environ.get("LUMACUT_DATA_ROOT","/data"))
ART=ROOT/"artifacts"
WORK=ROOT/"jobs"
ART.mkdir(parents=True,exist_ok=True)
WORK.mkdir(parents=True,exist_ok=True)
REPO=os.environ.get("GIT_REPOSITORY","git@github.com:theubyte/LumaCut-CNC.git")
BRANCH=os.environ.get("GIT_BRANCH","main")
PASSWORD=os.environ.get("BUILDER_PASSWORD","")
UPDATE_DEVICE_KEY=os.environ.get("UPDATE_DEVICE_KEY","")
UPDATE_PUBLIC_ORIGIN=os.environ.get("UPDATE_PUBLIC_ORIGIN","https://luma.millione.de").rstrip("/")
RELEASE_FILE=ROOT/"approved-release.json"
OTA_IMAGE_NAME="HMI_OTA_APP_UNVERIFIED.bin"
SKR_RELEASE_IMAGE_NAME="SKR_UART_UNVERIFIED_firmware.bin"
TARGETS={"tests","stm32_project_unverified","stm32_hmi_bridge_unverified","esp32_hmi_unverified","esp32_hmi_keypad_unverified","esp32_hmi_pro_unverified","lumacut_complete_suite_unverified"}
ID_RE=re.compile(r"^[a-f0-9]{16}$")
app=Flask(__name__)
lock=threading.Lock()
running=None
STAGES={
    "lumacut_complete_suite_unverified":["GitHub-Quellen","SKR grblHAL kompilieren","Waveshare HMI kompilieren","Komplettpaket erstellen"],
    "stm32_hmi_bridge_unverified":["GitHub-Quellen","SKR grblHAL kompilieren","Firmware vorbereiten"],
    "stm32_project_unverified":["GitHub-Quellen","SKR grblHAL kompilieren","Firmware vorbereiten"],
    "esp32_hmi_pro_unverified":["GitHub-Quellen","Waveshare HMI kompilieren","Flashpaket erstellen"],
    "esp32_hmi_unverified":["GitHub-Quellen","Waveshare HMI kompilieren","Flashpaket erstellen"],
    "esp32_hmi_keypad_unverified":["GitHub-Quellen","Waveshare HMI kompilieren","Flashpaket erstellen"],
    "tests":["GitHub-Quellen","Projekt-Tests","Pruefbericht erstellen"]
}
WEIGHTS={
    "lumacut_complete_suite_unverified":[0.08,0.38,0.44,0.10],
    "stm32_hmi_bridge_unverified":[0.09,0.81,0.10],
    "stm32_project_unverified":[0.09,0.81,0.10],
    "esp32_hmi_pro_unverified":[0.07,0.83,0.10],
    "esp32_hmi_unverified":[0.07,0.83,0.10],
    "esp32_hmi_keypad_unverified":[0.07,0.83,0.10],
    "tests":[0.12,0.80,0.08]
}
# Cold-start estimates until this machine has finished a job in each category.
# Clearly marked as approximations in the UI, not fabricated completion times.
BASELINE_SECONDS={
    "lumacut_complete_suite_unverified":1200,
    "stm32_hmi_bridge_unverified":330,
    "stm32_project_unverified":330,
    "esp32_hmi_pro_unverified":950,
    "esp32_hmi_unverified":950,
    "esp32_hmi_keypad_unverified":950,
    "tests":100
}

@app.before_request
def auth():
    # Public metadata enables checks; binaries require per-device token.
    if request.method=="GET" and request.path=="/api/updates/latest":
        return None
    if request.method=="GET" and request.path.startswith("/api/updates/file/"):
        supplied=request.headers.get("X-LumaCut-Device-Key","")
        if UPDATE_DEVICE_KEY and hmac.compare_digest(supplied,UPDATE_DEVICE_KEY):
            return None
    head=request.headers.get("Authorization","")
    try:
        payload=base64.b64decode(head[6:],validate=True).decode("utf-8") if head.startswith("Basic ") else ""
        user,password=payload.split(":",1)
        ok=bool(PASSWORD) and hmac.compare_digest(user,"lumacut") and hmac.compare_digest(password,PASSWORD)
    except (ValueError,UnicodeError):
        ok=False
    if not ok:
        return Response("Authentication required",401,{"WWW-Authenticate":'Basic realm="LumaCut Builder"'})
    if request.method=="POST" and request.headers.get("X-LumaCut-Action")!="build":
        abort(403)

def save(folder,obj):
    temp=folder/"manifest.tmp"
    temp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8")
    temp.replace(folder/"manifest.json")

def mark_stage(folder,meta,index):
    names=STAGES.get(meta["target"],["Build"])
    meta["stage_index"]=index
    meta["stage"]=names[min(index,len(names)-1)]
    meta["stage_started_utc"]=datetime.now(timezone.utc).isoformat()
    save(folder,meta)

def elapsed_seconds(meta):
    try:
        started=datetime.fromisoformat(meta.get("created_utc",""))
        stop=datetime.fromisoformat(meta.get("finished_utc","")) if meta.get("finished_utc") else datetime.now(timezone.utc)
        return max(0,int((stop-started).total_seconds()))
    except (ValueError,TypeError):
        return 0

def progress_info(meta):
    state=meta.get("status","")
    duration=elapsed_seconds(meta)
    if state in ("success","failed"):
        return {"progress_pct":100 if state=="success" else int(meta.get("progress_pct",0)),
                "elapsed_seconds":duration,"eta_seconds":0,"stage":meta.get("stage","Fertig"),
                "eta_source":"finished"}
    target=meta.get("target","")
    weight=WEIGHTS.get(target,[1.0])
    index=min(max(int(meta.get("stage_index",0)),0),len(weight)-1)
    base=sum(weight[:index])
    within=.08
    stage=meta.get("stage","Starte Build")
    file=ART/meta.get("id","")/"build.log"
    if file.is_file():
        try:
            with file.open("rb") as stream:
                stream.seek(max(0,file.stat().st_size-280000))
                text=stream.read().decode("utf-8",errors="replace")
            if index==0:
                within=.64 if "Cloning into" in text else .14
            elif "kompilieren" in stage:
                # Counts actual compiler output, never claims complete before
                # PlatformIO reports success.
                marker="lumacut_waveshare" if "HMI" in stage else "lumacut_skr"
                count=sum(1 for line in text.splitlines() if "Compiling .pio/build/" in line and marker in line)
                reference=410 if "HMI" in stage else 215
                within=min(.89,max(.02,count/reference))
                tail=text[-3500:]
                if "Linking .pio/build/" in tail and marker in tail: within=max(within,.93)
                if "Building .pio/build/" in tail and marker in tail: within=max(within,.96)
            else:
                within=.4
        except OSError:
            pass
    pct=min(98,max(0,int(100*(base+weight[index]*within))))
    prior=[]
    for job in ART.iterdir():
        if not job.is_dir() or job.name==meta.get("id"): continue
        m=job/"manifest.json"
        if not m.is_file(): continue
        try:
            v=json.loads(m.read_text(encoding="utf-8"))
            if v.get("target")==target and v.get("status")=="success":
                prior.append(elapsed_seconds(v))
        except (OSError,ValueError):
            pass
        if len(prior)>=16: break
    expected=int(median(prior)) if prior else BASELINE_SECONDS.get(target,600)
    # Blend time history with observed build progress after early startup.
    inferred=int(duration*(100-pct)/max(pct,1)) if duration>20 and pct>=10 else expected-duration
    eta=max(0,int(.6*max(0,expected-duration)+.4*max(0,inferred)))
    return {"progress_pct":pct,"elapsed_seconds":duration,"eta_seconds":eta,
            "stage":stage,"eta_source":"history" if prior else "baseline"}

def run(args,cwd,log,timeout):
    log.write("$ "+" ".join(args)+"\n")
    log.flush()
    process=subprocess.Popen(args,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        code=process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait()
        raise RuntimeError("Build timeout")
    if code:
        raise RuntimeError("Command failed: "+args[0]+" exit="+str(code))

def perform(job_id,target):
    global running
    folder=ART/job_id
    work=WORK/job_id
    folder.mkdir()
    work.mkdir()
    meta={"id":job_id,"target":target,"status":"running",
          "created_utc":datetime.now(timezone.utc).isoformat(),"repository":REPO,
          "branch":BRANCH,"source_sha":None,"flash_ready":False,"files":[],
          "stage_index":0,"stage":STAGES[target][0]}
    save(folder,meta)
    try:
        with (folder/"build.log").open("w",encoding="utf-8",buffering=1) as log:
            run(["git","clone","--depth","1","--branch",BRANCH,"--",REPO,str(work/"repo")],work,log,180)
            src=work/"repo"
            sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=src,text=True,timeout=20).strip()
            if not re.fullmatch("[a-f0-9]{40}",sha): raise RuntimeError("Invalid commit")
            meta["source_sha"]=sha
            save(folder,meta)
            log.write("SOURCE: "+sha+"\n")
            if target=="tests":
                mark_stage(folder,meta,1)
                run(["python","-m","unittest","discover","-s","tests","-v"],src,log,120)
                run(["python","-m","py_compile","builder/app.py","tools/probe_math.py"],src,log,60)
                mark_stage(folder,meta,2)
            elif target=="lumacut_complete_suite_unverified":
                # Build one source commit into a paired, self-contained release.
                skr=src/"firmware"/"skr"
                hmi=src/"firmware"/"hmi"
                mark_stage(folder,meta,1)
                run(["python","build.py","--bridge"],skr,log,2100)
                skr_out=skr/".pio"/"build"/"lumacut_skr_mz_hmi_uart"
                for fn in ("firmware.bin","firmware.elf"):
                    src_file=skr_out/fn
                    if not src_file.is_file(): raise RuntimeError("Missing SKR UART "+fn)
                    dst=folder/("SKR_UART_UNVERIFIED_"+fn)
                    shutil.copy2(src_file,dst)
                    meta["files"].append({"name":dst.name,"bytes":dst.stat().st_size,
                        "sha256":hashlib.sha256(dst.read_bytes()).hexdigest()})
                mark_stage(folder,meta,2)
                run(["pio","run","-e","lumacut_waveshare_s3_pro"],hmi,log,2100)
                hmi_out=hmi/".pio"/"build"/"lumacut_waveshare_s3_pro"
                meta["files"].extend(build_flash_package(hmi_out,folder,sha,
                    "lumacut_waveshare_s3_pro",Path(__file__).resolve().parent))
                mark_stage(folder,meta,3)
                # OTA requires the app-only image, never the merged 16 MB flash image.
                ota_src=hmi_out/"firmware.bin"
                if not ota_src.is_file(): raise RuntimeError("HMI OTA application is missing")
                ota_dest=folder/"HMI_OTA_APP_UNVERIFIED.bin"
                shutil.copy2(ota_src,ota_dest)
                meta["files"].append({"name":ota_dest.name,"bytes":ota_dest.stat().st_size,
                    "sha256":hashlib.sha256(ota_dest.read_bytes()).hexdigest()})
                release=folder/"LumaCut-Control-OS-Komplettpaket.zip"
                with zipfile.ZipFile(release,"w",zipfile.ZIP_DEFLATED) as z:
                    z.write(folder/"SKR_UART_UNVERIFIED_firmware.bin",
                            "SKR-Mini-MZ/firmware.bin")
                    z.write(folder/"SKR_UART_UNVERIFIED_firmware.elf",
                            "SKR-Mini-MZ/firmware.elf")
                    z.write(folder/"HMI_OTA_APP_UNVERIFIED.bin",
                            "Waveshare/HMI_OTA_APP_UNVERIFIED.bin")
                    z.write(folder/IMAGE_NAME,"Waveshare/"+IMAGE_NAME)
                    z.write(folder/"Waveshare-HMI-Flash-Paket-Windows.zip",
                            "Waveshare/Waveshare-HMI-Flash-Paket-Windows.zip")
                    z.write(src/"docs"/"LUMACUT_CONTROL_OS.md",
                            "DOKUMENTATION/ANLEITUNG.md")
                    z.writestr("ZUERST_LESEN.txt",
                        "LUMACUT CONTROL OS - ENTWICKLUNGSSTAND\n"
                        "Beide Firmwaredateien aus genau demselben Git-Commit.\n"
                        "Waveshare zuerst per Windows-Flashpaket installieren.\n"
                        "SKR benötigt UART-Hauptstream (kein altes Keypad).\n"
                        "Niemals flashen oder Maschinenbewegungen auslösen, bevor\n"
                        "Pinbelegung, Bootloader, Endschalter, Schutzkette und\n"
                        "hardwarewirksamer Laser-Not-Aus geprüft wurden.\n"
                        "Laser während Erstinbetriebnahme stromlos und TTL getrennt.\n")
                meta["files"].append({"name":release.name,"bytes":release.stat().st_size,
                    "sha256":hashlib.sha256(release.read_bytes()).hexdigest()})
                meta["flash_package"]=True
                meta["paired_firmware"]=True
                log.write("PAIRED LUMACUT CONTROL OS: SKR UART + Waveshare PRO, one source SHA.\n")
            else:
                key="skr" if target.startswith("stm32_") else "hmi"
                env=("lumacut_skr_mz_hmi_uart" if target=="stm32_hmi_bridge_unverified"
                     else "lumacut_skr_mz_usb" if key=="skr"
                     else "lumacut_waveshare_s3_pro" if target=="esp32_hmi_pro_unverified"
                     else "lumacut_waveshare_s3_keypad" if target=="esp32_hmi_keypad_unverified"
                     else "lumacut_waveshare_s3")
                project=src/"firmware"/key
                if not (project/"platformio.ini").is_file():
                    raise RuntimeError("Firmware not implemented yet: firmware/"+key+"/platformio.ini missing")
                mark_stage(folder,meta,1)
                if key=="skr":
                    run(["python","build.py"]+(["--bridge"] if target=="stm32_hmi_bridge_unverified" else []),project,log,2100)
                else:
                    run(["pio","run","-e",env],project,log,2100)
                found=False
                output=project/".pio"/"build"/env
                for filename in ("firmware.bin","firmware.elf","bootloader.bin","partitions.bin"):
                    f=output/filename
                    if not f.is_file(): continue
                    name="UNVERIFIED_DO_NOT_FLASH_"+filename
                    dest=folder/name
                    shutil.copyfile(f,dest)
                    meta["files"].append({"name":name,"bytes":dest.stat().st_size,
                        "sha256":hashlib.sha256(dest.read_bytes()).hexdigest()})
                    found=True
                if not found: raise RuntimeError("Build produced no firmware artifact")
                mark_stage(folder,meta,2)
                if key=="hmi":
                    # Complete HMI image is flashable, but not hardware-validated.
                    flash_files=build_flash_package(
                        output,folder,sha,env,Path(__file__).resolve().parent
                    )
                    meta["files"].extend(flash_files)
                    meta["flash_package"]=True
                    log.write("ESP32-S3 image + Windows localhost flash package ready.\n")
            meta["status"]="success"
            meta["stage"]="Abgeschlossen"
            meta["progress_pct"]=100
    except Exception as exc:
        meta["progress_pct"]=progress_info(meta)["progress_pct"]
        meta["status"]="failed"
        meta["stage"]="Fehlgeschlagen"
        meta["error"]=str(exc)
        with (folder/"build.log").open("a",encoding="utf-8") as log: log.write("\nERROR: "+str(exc)+"\n")
    finally:
        meta["finished_utc"]=datetime.now(timezone.utc).isoformat()
        save(folder,meta)
        with zipfile.ZipFile(folder/"build-package.zip","w",zipfile.ZIP_DEFLATED) as z:
            for name in ("manifest.json","build.log"):
                if (folder/name).is_file(): z.write(folder/name,name)
            for f in meta["files"]: z.write(folder/f["name"],f["name"])
        shutil.rmtree(work,ignore_errors=True)
        with lock:
            if running==job_id: running=None

@app.get("/api/jobs")
def jobs():
    result=[]
    for folder in ART.iterdir():
        if folder.is_dir() and ID_RE.fullmatch(folder.name) and (folder/"manifest.json").is_file():
            try:
                meta=json.loads((folder/"manifest.json").read_text())
                if meta.get("paired_firmware") and meta.get("status")=="success":
                    ready,reason=release_readiness(meta,folder)
                    meta["release_ready"]=ready
                    meta["release_blocker"]=reason
                result.append(meta)
            except (ValueError,OSError,TypeError,KeyError): continue
    with lock: current=running
    result=sorted(result,key=lambda m:m.get("created_utc",""),reverse=True)[:50]
    for item in result:
        item.update(progress_info(item))
    return jsonify({"active":current,"jobs":result,"server_utc":datetime.now(timezone.utc).isoformat()})

@app.post("/api/build")
def build():
    global running
    body=request.get_json(silent=True)
    target=body.get("target") if isinstance(body,dict) else None
    if target not in TARGETS: abort(400)
    with lock:
        if running: return jsonify({"error":"Another job is running","active":running}),409
        job_id=secrets.token_hex(8)
        running=job_id
    threading.Thread(target=perform,args=(job_id,target),daemon=True).start()
    return jsonify({"id":job_id}),202

@app.get("/api/jobs/<job_id>/log")
def get_log(job_id):
    if not ID_RE.fullmatch(job_id): abort(404)
    file=ART/job_id/"build.log"
    if not file.is_file(): abort(404)
    with file.open("rb") as f:
        f.seek(0,2)
        f.seek(max(0,f.tell()-120000))
        value=f.read().decode(errors="replace")
    return Response(value,mimetype="text/plain")

@app.get("/api/jobs/<job_id>/flash-manifest.json")
def get_flash_manifest(job_id):
    if not ID_RE.fullmatch(job_id): abort(404)
    manifest=ART/job_id/"manifest.json"
    if not manifest.is_file(): abort(404)
    meta=json.loads(manifest.read_text(encoding="utf-8"))
    if meta.get("status")!="success" or not meta.get("flash_package"): abort(404)
    if meta.get("target") not in ("esp32_hmi_unverified","esp32_hmi_keypad_unverified","esp32_hmi_pro_unverified","lumacut_complete_suite_unverified"): abort(404)
    if not (ART/job_id/IMAGE_NAME).is_file(): abort(404)
    return jsonify(flash_manifest(
        "/artifacts/"+job_id+"/"+IMAGE_NAME,
        (meta.get("source_sha") or "unknown")[:12]+"-"+meta["target"]
    ))


@app.get("/artifacts/<job_id>/<filename>")
def get_artifact(job_id,filename):
    if not ID_RE.fullmatch(job_id): abort(404)
    folder=ART/job_id
    m=folder/"manifest.json"
    if not m.is_file(): abort(404)
    allowed={"manifest.json","build.log","build-package.zip"}
    allowed.update(x["name"] for x in json.loads(m.read_text()).get("files",[]))
    if filename not in allowed: abort(404)
    return send_from_directory(folder,filename,as_attachment=True)

def release_readiness(meta,folder):
    """Lightweight presence/manifest gate for the dashboard; no costly rehash.

    Existing paired builds from older compiler versions can legitimately lack
    the HMI OTA application file. They remain downloadable as normal archives,
    but MUST NOT be advertised as installable OTA releases.
    """
    if (meta.get("status")!="success" or
        meta.get("target")!="lumacut_complete_suite_unverified" or
        not meta.get("paired_firmware")):
        return False,"Nur erfolgreiches Komplettpaket (HMI + SKR) freigeben."
    if not re.fullmatch(r"[a-f0-9]{40}",meta.get("source_sha") or ""):
        return False,"Der Build hat keine gueltige Git-Quellversion."
    records={f.get("name"):f for f in meta.get("files",[]) if isinstance(f,dict)}
    for name in (OTA_IMAGE_NAME,SKR_RELEASE_IMAGE_NAME):
        record=records.get(name)
        image=folder/name
        if (not record or not image.is_file() or
            not isinstance(record.get("bytes"),int) or
            not isinstance(record.get("sha256"),str) or
            not re.fullmatch(r"[a-f0-9]{64}",record["sha256"]) or
            record["bytes"]<=0 or record["bytes"]!=image.stat().st_size):
            if name==OTA_IMAGE_NAME:
                return False,(
                    "Diesem aelteren Build fehlt das separat gepruefte HMI-OTA-Image. "
                    "Bitte neues 'Komplett HMI + grblHAL'-Build aus main starten "
                    "und danach den NEUEN Build freigeben."
                )
            return False,(
                "Das SKR-Update-Image fehlt oder ist unvollstaendig. "
                "Bitte ein neues Komplett-Build erstellen."
            )
    return True,""

def validated_release(job_id):
    if not ID_RE.fullmatch(job_id): raise ValueError("Invalid build id")
    folder=ART/job_id
    path=folder/"manifest.json"
    if not path.is_file(): raise ValueError("Build manifest missing")
    meta=json.loads(path.read_text(encoding="utf-8"))
    ready,reason=release_readiness(meta,folder)
    if not ready: raise ValueError(reason)
    names={"hmi":OTA_IMAGE_NAME,"skr":SKR_RELEASE_IMAGE_NAME}
    records={f["name"]:f for f in meta.get("files",[])}
    images={}
    for role,name in names.items():
        file=folder/name
        if not file.is_file() or name not in records:
            raise ValueError("Missing firmware image "+name)
        with file.open("rb") as stream:
            digest=hashlib.file_digest(stream,"sha256").hexdigest()
        if digest!=records[name]["sha256"]:
            raise ValueError("Firmware-Pruefsumme ungueltig: "+name+
                             ". Bitte neues Komplett-Build erstellen.")
        images[role]={"bytes":file.stat().st_size,"sha256":digest,
            "url":UPDATE_PUBLIC_ORIGIN+"/api/updates/file/"+role}
    return {"schema":1,"channel":"stable","paired":True,"job_id":job_id,
        "source_sha":meta["source_sha"],"hardware":{
            "hmi":"Waveshare ESP32-S3-Touch-LCD-7 Rev1.2",
            "skr":"BTT SKR Mini MZ V1.0 STM32F103RC"},
        "hmi_ota_enabled":True,
        "skr_firmware_available":True,
        "skr_install_method":"microSD",
        "skr_install_filename":"firmware.bin",
        "images":images}

@app.post("/api/updates/approve")
def approve_update():
    # Only the authenticated administrator can publish. A new build alone
    # never pushes potentially defective firmware to an attached laser.
    body=request.get_json(silent=True)
    if not isinstance(body,dict): abort(400)
    try: manifest=validated_release(body.get("job_id",""))
    except (ValueError,OSError,KeyError) as ex:
        return jsonify({"error":str(ex)}),400
    manifest["published_utc"]=datetime.now(timezone.utc).isoformat()
    tmp=ROOT/"approved-release.tmp"
    tmp.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    tmp.replace(RELEASE_FILE)
    return jsonify(manifest)

@app.get("/api/updates/latest")
def latest_update():
    if not RELEASE_FILE.is_file():
        response=jsonify({"available":False,"schema":1,"channel":"stable"})
    else:
        try:
            manifest=json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
            response=jsonify({"available":True,**manifest})
        except (OSError,ValueError):
            response=jsonify({"available":False,"error":"Invalid release data"})
            response.status_code=503
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    return response

@app.get("/api/updates/skr-firmware.bin")
def download_approved_skr_sd():
    """Same approved SKR image as the release, named for the board's SD bootloader.

    This route remains behind the normal dashboard login. It never claims that
    merely downloading the image automatically writes the board flash.
    """
    if not RELEASE_FILE.is_file(): abort(404)
    manifest=json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    try:
        checked=validated_release(manifest.get("job_id",""))
    except (ValueError,OSError,KeyError): abort(503)
    if checked["source_sha"]!=manifest.get("source_sha"): abort(503)
    image=ART/manifest["job_id"]/SKR_RELEASE_IMAGE_NAME
    response=send_file(image,as_attachment=True,download_name="firmware.bin",
                       mimetype="application/octet-stream",max_age=0)
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    return response

@app.get("/api/updates/file/<role>")
def update_image(role):
    if role not in ("hmi","skr"): abort(404)
    if not UPDATE_DEVICE_KEY:
        return jsonify({"error":"Update device key is not configured"}),503
    if not RELEASE_FILE.is_file(): abort(404)
    manifest=json.loads(RELEASE_FILE.read_text(encoding="utf-8"))
    job_id=manifest.get("job_id","")
    try: checked=validated_release(job_id)
    except (ValueError,OSError,KeyError): abort(503)
    if checked["source_sha"]!=manifest.get("source_sha"): abort(503)
    filename=OTA_IMAGE_NAME if role=="hmi" else SKR_RELEASE_IMAGE_NAME
    response=send_file(ART/job_id/filename,mimetype="application/octet-stream",
        as_attachment=True,download_name=filename,max_age=0)
    response.headers["Cache-Control"]="no-store"
    return response

@app.get("/api/jobs/<job_id>/sd-image")
def sd_image(job_id):
    """Download board-specific SKR image with required SD filename firmware.bin."""
    if not ID_RE.fullmatch(job_id): abort(404)
    manifest=ART/job_id/"manifest.json"
    if not manifest.is_file(): abort(404)
    meta=json.loads(manifest.read_text(encoding="utf-8"))
    if meta.get("status")!="success": abort(409)
    if meta.get("target") not in (
        "lumacut_complete_suite_unverified",
        "stm32_project_unverified",
        "stm32_hmi_bridge_unverified"
    ): abort(404)
    name=("SKR_UART_UNVERIFIED_firmware.bin"
          if meta.get("paired_firmware") else "UNVERIFIED_DO_NOT_FLASH_firmware.bin")
    file=ART/job_id/name
    if not file.is_file(): abort(404)
    return send_file(file,as_attachment=True,download_name="firmware.bin",
                     mimetype="application/octet-stream",max_age=0)

@app.get("/ui/<asset>")
def frontend_asset(asset):
    if asset not in {"dashboard.css","dashboard.js"}: abort(404)
    return send_file(Path(__file__).resolve().parent/asset,max_age=0)

@app.get("/")
def home():
    return send_file(Path(__file__).resolve().parent/"dashboard.html",
                     mimetype="text/html",max_age=0)


if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080,threaded=True)
