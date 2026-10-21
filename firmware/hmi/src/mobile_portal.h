#pragma once
// Captive-independent LAN-only operator UI. API refuses control without passcode
// and without recent local HMI authorization for potentially hazardous actions.
static const char MOBILE_PORTAL[] PROGMEM = R"LCWEB(
<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>LumaCut Control</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#15181e;background:#f4f6fa}
*{box-sizing:border-box}body{margin:0}main{max-width:760px;margin:auto;padding:24px 20px 100px}
h1{font-size:30px;letter-spacing:-1px;margin:4px 0}small,.hint{color:#697581}
h2{margin:0 0 15px;font-size:18px}header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
.brand{font-weight:800;font-size:14px;color:#007aff}article{background:white;border:1px solid #e7eaf0;border-radius:24px;padding:20px;margin:12px 0;box-shadow:0 8px 30px #1929430a}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}button{appearance:none;background:#eff3f9;border:0;border-radius:15px;padding:15px;font-size:15px;font-weight:650;color:#1a2736;cursor:pointer}
button.blue{background:#007aff;color:#fff}button.red{background:#ffebec;color:#b31c32}button:disabled{opacity:.45}
input{border:1px solid #dfe4eb;background:#fafbfc;border-radius:13px;padding:13px;font-size:16px;max-width:100%;width:100%}
input[type=file]{font-size:13px}.space{height:9px}
#log{color:#66778a;font-size:13px;min-height:30px;overflow-wrap:anywhere}
#jobs>button{display:block;width:100%;text-align:left;margin-bottom:8px}
nav{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);display:flex;background:#fffefaed;
border:1px solid #dfe4e8;border-radius:28px;padding:8px;box-shadow:0 9px 30px #13294020;gap:6px}
nav button{padding:11px 18px;border-radius:19px;background:transparent;white-space:nowrap}
nav button.sel{background:#e5f1ff;color:#007aff}
.tab{display:none}.tab.active{display:block}
.status{display:flex;justify-content:space-between;align-items:center}.pill{border-radius:12px;background:#eaf3ff;color:#1761bb;padding:5px 11px;font-size:13px}
code{font-size:13px;word-break:break-word}
</style>
<main><header><div><div class="brand">LUMACUT · CONTROL OS</div><h1>Laser Studio</h1></div><span id="connection" class="pill">Verbinde …</span></header>
<div class="tab active" id="home">
<article><h2>Maschinenstatus</h2><div class="status"><strong id="state">Unbekannt</strong><span id="owner" class="hint">–</span></div><p class="hint" id="pos">X — · Y — · Z —</p><p class="hint" id="wifi"></p></article>
<article><h2>Aufträge</h2><div id="jobinfo" class="hint">Kein Job gewählt</div><div class="space"></div>
<div class="grid"><button onclick="act('frame')">Rahmen ohne Laser</button><button class="blue" onclick="act('start')">Start anfordern</button><button onclick="act('pause')">Pause</button><button onclick="act('resume')">Fortsetzen</button><button class="red" onclick="act('abort')">Abbrechen</button><button onclick="act('park')">Parkposition</button></div>
<p class="hint">Start und Bewegung erfordern die lokale Freigabe am Bildschirm. Laservorschau mit 1 % ist nicht remote freigegeben.</p></article></div>
<div class="tab" id="files"><article><h2>G-Code hochladen</h2>
<input id="up" type="file" accept=".gcode,.nc,.tap,.txt"><div class="space"></div><button class="blue" onclick="upload()">Auf HMI laden</button>
<p class="hint">G-Code-Dateien. Keine LightBurn-Projektdateien (.lbrn2). LightBurn kann Aufträge stattdessen über USB oder Wi-Fi/TCP übertragen.</p></article>
<article><h2>Gespeicherte Dateien</h2><div id="jobs"></div></article></div>
<div class="tab" id="device"><article><h2>Verbindung und Zugang</h2>
<p>Gerät: <strong id="ip">–</strong></p><label>HMI-Zugangscode</label><input id="key" type="password" placeholder="Code vom HMI-Display">
<div class="space"></div><button onclick="savekey()">Zugang speichern</button><p class="hint">Nur im lokalen WLAN nutzen. API-Zugangscode niemals veröffentlichen.</p></article></div>
<div id="log"></div>
</main>
<nav><button class="sel" onclick="tab('home',this)">Übersicht</button><button onclick="tab('files',this)">Dateien</button><button onclick="tab('device',this)">Gerät</button></nav>
<script>
let key=sessionStorage.getItem('lc-key')||'';
document.querySelector('#key').value=key;
function tab(name,button){document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.id===name));document.querySelectorAll('nav button').forEach(x=>x.classList.remove('sel'));button.classList.add('sel')}
function savekey(){key=document.querySelector('#key').value.trim();sessionStorage.setItem('lc-key',key);msg('Zugang lokal im Browser gespeichert');poll()}
function msg(s){document.querySelector('#log').textContent=s}
async function api(path,options){const sep=path.includes('?')?'&':'?';let response=await fetch(path+sep+'key='+encodeURIComponent(key),options);if(!response.ok)throw Error((await response.text()).slice(0,200));return response.json()}
async function poll(){if(!key){msg('Zugangscode unter Gerät eingeben');return}try{
 const s=await api('/api/status');document.querySelector('#state').textContent=s.state||'?';
 document.querySelector('#owner').textContent=s.owner;document.querySelector('#pos').textContent=s.position;
 document.querySelector('#wifi').textContent=s.message||'';document.querySelector('#ip').textContent=location.host;
 document.querySelector('#jobinfo').textContent=s.job||'Kein Job gewählt';
 document.querySelector('#connection').textContent='Verbunden';
 const data=await api('/api/jobs');const target=document.querySelector('#jobs');target.replaceChildren();
 for(const f of data.files){let b=document.createElement('button');b.textContent=f.name+' · '+Math.round(f.bytes/1024)+' KB';
 b.onclick=async()=>{try{await api('/api/select',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'name='+encodeURIComponent(f.name)});msg('Ausgewählt: '+f.name);poll()}catch(e){msg(e.message)}};target.appendChild(b)}
 }catch(e){document.querySelector('#connection').textContent='Getrennt';msg(e.message)}}
async function act(op){try{await api('/api/action',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'op='+encodeURIComponent(op)});msg('Angefordert: '+op);poll()}catch(e){msg('Nicht ausgeführt: '+e.message)}}
async function upload(){let f=document.querySelector('#up').files[0];if(!f){msg('Datei auswählen');return}let form=new FormData();form.append('file',f,f.name);
 try{await api('/api/upload',{method:'POST',body:form});msg('Hochgeladen: '+f.name);poll()}catch(e){msg(e.message)}}
poll();setInterval(poll,3000);
</script></html>
)LCWEB";
