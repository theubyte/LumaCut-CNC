"""LumaCut: authenticated LAN build dashboard. Fixed targets only, no flash commands."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import base64, hashlib, hmac, json, os, re, secrets, shutil, signal, subprocess, threading, zipfile
from flask import Flask, Response, request, abort, jsonify, send_from_directory

ROOT=Path("/data")
ART=ROOT/"artifacts"
WORK=ROOT/"jobs"
ART.mkdir(parents=True,exist_ok=True)
WORK.mkdir(parents=True,exist_ok=True)
REPO=os.environ.get("GIT_REPOSITORY","git@github.com:theubyte/LumaCut-CNC.git")
BRANCH=os.environ.get("GIT_BRANCH","main")
PASSWORD=os.environ.get("BUILDER_PASSWORD","")
TARGETS={"tests","stm32_project_unverified","esp32_hmi_unverified"}
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
                key="skr" if target=="stm32_project_unverified" else "hmi"
                env="lumacut_skr_mz_usb" if key=="skr" else "lumacut_waveshare_s3"
                project=src/"firmware"/key
                if not (project/"platformio.ini").is_file():
                    raise RuntimeError("Firmware not implemented yet: firmware/"+key+"/platformio.ini missing")
                if key=="skr":
                    run(["python","build.py"],project,log,2100)
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
<style>body{background:#101721;color:#edf5fa;font-family:system-ui;margin:0}
main{max-width:1050px;margin:auto;padding:24px}h1{font-size:38px}
p,small{color:#aec1d0}section{background:#1b2939;border:1px solid #344357;
border-radius:18px;padding:20px;margin:16px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:720px){.grid{grid-template-columns:1fr}}
button{background:#68dac5;color:#072920;border:0;border-radius:10px;padding:12px;font-weight:700;cursor:pointer}
a{color:#79e0d7}li{margin:14px 0;overflow-wrap:anywhere}
pre{background:#0c1119;white-space:pre-wrap;word-break:break-word;padding:16px;max-height:380px;overflow:auto}</style>
<main><h1>LumaCut Build Lab</h1><p>Private GitHub-Quellen · geprüfter Commit · Buildarchiv und Prüfsumme · keine automatische Flashfunktion.</p>
<div class="grid"><section><h2>Build starten</h2><p><button onclick="start('tests')">Projekt-Tests</button></p>
<p><button onclick="start('stm32_project_unverified')">SKR MZ kompilieren</button></p>
<p><button onclick="start('esp32_hmi_unverified')">Waveshare HMI kompilieren</button></p>
<p style="color:#ffcb81">SKR- und HMI-Quellen sind noch nicht implementiert; auch erzeugte Builds wären nicht flashfreigegeben.</p>
<div id="message"></div></section><section><h2>Buildhistorie</h2><ul id="jobs"></ul></section></div>
<section><h2>Protokoll</h2><pre id="log">Kein Build gewählt.</pre></section>
<p>Nur LAN / VPN · HTTP Basic Auth ohne TLS nicht ins Internet freigeben.</p>
<script>
let current='';
async function start(t){try{let r=await fetch('/api/build',{method:'POST',
headers:{'Content-Type':'application/json','X-LumaCut-Action':'build'},body:JSON.stringify({target:t})});
let d=await r.json();if(!r.ok)throw Error(d.error||r.status);current=d.id;refresh()}
catch(e){document.querySelector('#message').textContent=String(e)}}
function escapeHtml(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
async function show(id){current=id;let r=await fetch('/api/jobs/'+id+'/log');
if(r.ok)document.querySelector('#log').textContent=await r.text()}
async function refresh(){try{let r=await fetch('/api/jobs');let d=await r.json();
document.querySelector('#jobs').innerHTML=(d.jobs||[]).map(j=>'<li><b>'+escapeHtml(j.target)+'</b> '+escapeHtml(j.status)+
'<br><small>'+escapeHtml((j.source_sha||'').slice(0,12))+'</small><br>'+
'<a href="#" data-id="'+j.id+'">Log</a> · <a href="/artifacts/'+j.id+'/build-package.zip">ZIP</a> · '+
'<a href="/artifacts/'+j.id+'/manifest.json">Manifest</a></li>').join('');
document.querySelectorAll('[data-id]').forEach(a=>a.onclick=e=>{e.preventDefault();show(a.dataset.id)});
if(current)show(current)}catch(e){document.querySelector('#message').textContent='Fehler: '+e}}
refresh();setInterval(refresh,4000);
</script></main></html>""",mimetype="text/html")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080,threaded=True)
