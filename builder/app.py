"""LumaCut: authenticated LAN build dashboard with HMI flashing packages."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import base64, hashlib, hmac, json, os, re, secrets, shutil, signal, subprocess, threading, zipfile
from flask import Flask, Response, request, abort, jsonify, send_from_directory
from flash_bundle import build_flash_package, flash_manifest, IMAGE_NAME

ROOT=Path("/data")
ART=ROOT/"artifacts"
WORK=ROOT/"jobs"
ART.mkdir(parents=True,exist_ok=True)
WORK.mkdir(parents=True,exist_ok=True)
REPO=os.environ.get("GIT_REPOSITORY","git@github.com:theubyte/LumaCut-CNC.git")
BRANCH=os.environ.get("GIT_BRANCH","main")
PASSWORD=os.environ.get("BUILDER_PASSWORD","")
TARGETS={"tests","stm32_project_unverified","stm32_hmi_bridge_unverified","esp32_hmi_unverified","esp32_hmi_keypad_unverified","esp32_hmi_pro_unverified"}
ID_RE=re.compile(r"^[a-f0-9]{16}$")
app=Flask(__name__)
lock=threading.Lock()
running=None

@app.before_request
def auth():
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
          "branch":BRANCH,"source_sha":None,"flash_ready":False,"files":[]}
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
                run(["python","-m","unittest","discover","-s","tests","-v"],src,log,120)
                run(["python","-m","py_compile","builder/app.py","tools/probe_math.py"],src,log,60)
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
                if key=="hmi":
                    # Complete HMI image is flashable, but not hardware-validated.
                    flash_files=build_flash_package(
                        output,folder,sha,env,Path(__file__).resolve().parent
                    )
                    meta["files"].extend(flash_files)
                    meta["flash_package"]=True
                    log.write("ESP32-S3 image + Windows localhost flash package ready.\n")
            meta["status"]="success"
    except Exception as exc:
        meta["status"]="failed"
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
            try: result.append(json.loads((folder/"manifest.json").read_text()))
            except (ValueError,OSError): continue
    with lock: current=running
    return jsonify({"active":current,"jobs":sorted(result,key=lambda m:m["created_utc"],reverse=True)[:50]})

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
    if meta.get("target") not in ("esp32_hmi_unverified","esp32_hmi_keypad_unverified","esp32_hmi_pro_unverified"): abort(404)
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

@app.get("/")
def home():
    return Response("""<!doctype html><html lang="de"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>LumaCut Build Lab</title>
<script type="module" src="https://unpkg.com/esp-web-tools@10/dist/web/install-button.js?module"></script>
<style>body{background:#101721;color:#edf5fa;font-family:system-ui;margin:0}
main{max-width:1050px;margin:auto;padding:24px}h1{font-size:38px}
esp-web-install-button{--esp-tools-button-color:#68dac5;--esp-tools-button-text-color:#072920}
p,small{color:#aec1d0}section{background:#1b2939;border:1px solid #344357;
border-radius:18px;padding:20px;margin:16px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:720px){.grid{grid-template-columns:1fr}}
button{background:#68dac5;color:#072920;border:0;border-radius:10px;padding:12px;font-weight:700;cursor:pointer}
a{color:#79e0d7}li{margin:14px 0;overflow-wrap:anywhere}
pre{background:#0c1119;white-space:pre-wrap;word-break:break-word;padding:16px;max-height:380px;overflow:auto}</style>
<main><h1>LumaCut Build Lab</h1><p>GitHub-Quellen · Buildarchiv und SHA256 · Waveshare ESP32-S3 per Browser oder Windows-Flashpaket installieren.</p>
<div class="grid"><section><h2>Build starten</h2><p><button onclick="start('tests')">Projekt-Tests</button></p>
<p><button onclick="start('stm32_project_unverified')">SKR USB (alt) bauen</button></p>
<p><button onclick="start('stm32_hmi_bridge_unverified')">SKR UART für Control OS bauen</button></p>
<p><button onclick="start('esp32_hmi_unverified')">Waveshare HMI (nur Touch) bauen</button></p>
<p><button onclick="start('esp32_hmi_keypad_unverified')">Waveshare HMI (UART-Jog, Labor) bauen</button></p>
<p><button onclick="start('esp32_hmi_pro_unverified')">LumaCut Control OS (USB/WLAN/Jobs) bauen</button></p>
<p style="color:#ffcb81">Entwicklungsfirmware, nicht hardwareverifiziert! Zuerst Touch-Version ohne Motorsteuerung flashen. Laser physisch von Versorgung und TTL trennen.</p>
<p>Unter HTTP: fertiges Windows-Flashpaket herunterladen, entpacken und <code>Flash-Waveshare-Windows.cmd</code> starten (Python 3 und Chrome/Edge). Unter HTTPS ist der direkte Flashknopf verfügbar.</p>
<div id="message"></div></section><section><h2>Buildhistorie</h2><ul id="jobs"></ul></section></div>
<section id="flasharea"><h2>Waveshare über PC-USB flashen (HTTPS)</h2>
<p>Im LAN über HTTP bitte das Windows-Flashpaket herunterladen. Bei HTTPS einen abgeschlossenen HMI-Build in der Liste zum Flashen auswählen.</p>
<div id="flashpanel">Noch kein HMI-Build zum Flashen gewählt.</div></section>
<section><h2>Protokoll</h2><pre id="log">Kein Build gewählt.</pre></section>
<p>Nur LAN / VPN · HTTP Basic Auth ohne TLS nicht ins Internet freigeben.</p>
<script>
let current='';
async function start(t){try{let r=await fetch('/api/build',{method:'POST',
headers:{'Content-Type':'application/json','X-LumaCut-Action':'build'},body:JSON.stringify({target:t})});
let d=await r.json();if(!r.ok)throw Error(d.error||r.status);current=d.id;refresh()}
catch(e){document.querySelector('#message').textContent=String(e)}}
function escapeHtml(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function chooseFlash(id){
  if(!window.isSecureContext){
    document.querySelector('#message').textContent='USB-Flash im Browser benötigt HTTPS. Bitte Windows-Flashpaket nutzen.';
    return;
  }
  const installer=document.createElement('esp-web-install-button');
  installer.setAttribute('manifest','/api/jobs/'+id+'/flash-manifest.json');
  document.querySelector('#flashpanel').replaceChildren(installer);
  document.querySelector('#flasharea').scrollIntoView({behavior:'smooth'});
}
async function show(id){current=id;let r=await fetch('/api/jobs/'+id+'/log');
if(r.ok)document.querySelector('#log').textContent=await r.text()}
async function refresh(){try{let r=await fetch('/api/jobs');let d=await r.json();
document.querySelector('#jobs').innerHTML=(d.jobs||[]).map(j=>'<li><b>'+escapeHtml(j.target)+'</b> '+escapeHtml(j.status)+
'<br><small>'+escapeHtml((j.source_sha||'').slice(0,12))+'</small><br>'+
'<a href="#" data-id="'+j.id+'">Log</a> · <a href="/artifacts/'+j.id+'/build-package.zip">ZIP</a> · '+
'<a href="/artifacts/'+j.id+'/manifest.json">Manifest</a>'+
(j.status==='success' && j.flash_package
  ? '<br><a href="/artifacts/'+j.id+'/Waveshare-HMI-Flash-Paket-Windows.zip">Windows-Flashpaket</a> · '+
    '<a href="/artifacts/'+j.id+'/LUMACUT_HMI_ESP32S3_MERGED.bin">ESP32-S3 Komplett-BIN</a>'+
    (window.isSecureContext
       ? '<br><a href="#" data-flash="'+j.id+'">Jetzt per PC-USB flashen</a>'
       : '<br><small>Direkt im Browser flashen benötigt HTTPS. Über HTTP das Windows-Flashpaket verwenden.</small>')
  : '')+'</li>').join('');
document.querySelectorAll('[data-id]').forEach(a=>a.onclick=e=>{e.preventDefault();show(a.dataset.id)});
document.querySelectorAll('[data-flash]').forEach(a=>a.onclick=e=>{e.preventDefault();chooseFlash(a.dataset.flash)});
if(current)show(current)}catch(e){document.querySelector('#message').textContent='Fehler: '+e}}
refresh();setInterval(refresh,4000);
</script></main></html>""",mimetype="text/html")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080,threaded=True)
