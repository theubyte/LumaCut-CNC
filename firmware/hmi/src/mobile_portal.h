#pragma once
// Captive-independent LAN-only operator UI. API refuses control without passcode
// and without recent local HMI authorization for potentially hazardous actions.
static const char MOBILE_PORTAL[] PROGMEM = R"LCWEB(
<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>LumaCut Control</title>
<style>
:root{font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#f2f7ff;background:#091321}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(circle at 100% -15%,#163956 0,transparent 33%),#091321}
main{max-width:780px;margin:auto;padding:26px 20px 118px}
h1{font-size:34px;font-weight:780;letter-spacing:-1.1px;margin:5px 0;color:#f3f9ff}
small,.hint{color:#a4b4c7;line-height:1.55}
h2{font-size:18px;letter-spacing:-.3px;margin:0 0 17px;color:#f2f7ff}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:25px}
.brand{font-weight:800;font-size:12px;letter-spacing:2px;color:#39c7f6}
article{background:#172638;border:1px solid #284059;border-radius:23px;padding:21px;margin:13px 0;box-shadow:0 10px 30px #03081345}
article>p:last-child{margin-bottom:0}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:11px}
button{appearance:none;min-height:49px;background:#26384d;border:1px solid #35506b;border-radius:13px;padding:12px 13px;font:650 14px/1.3 inherit;color:#f2f7ff;cursor:pointer;transition:background .18s,transform .18s}
button:active{transform:scale(.98)}
button.blue{background:#39c7f6;color:#091321;border-color:#39c7f6}
button.red{background:#55303a;color:#ff9ea7;border-color:#663845}
button:disabled{opacity:.45}
input{border:1px solid #35506b;background:#26384d;color:#f2f7ff;border-radius:12px;padding:13px;font-size:16px;max-width:100%;width:100%}
input:focus{outline:2px solid #39c7f6;outline-offset:1px}
input[type=file]{font-size:13px}
.space{height:11px}
#log{color:#b6cbe0;font-size:13px;min-height:30px;margin:16px 4px;overflow-wrap:anywhere}
#jobs>button{display:block;width:100%;text-align:left;margin-bottom:9px}
nav{position:fixed;z-index:10;bottom:15px;left:50%;transform:translateX(-50%);display:flex;justify-content:space-between;max-width:760px;width:calc(100% - 24px);background:#172638ed;backdrop-filter:blur(16px);border:1px solid #35506b;border-radius:23px;padding:8px;box-shadow:0 10px 36px #030813a6;gap:5px}
nav button{min-width:0;flex:1;padding:11px 9px;border:0;border-radius:16px;background:transparent;color:#a4b4c7;white-space:nowrap}
nav button.sel{background:#153b54;color:#39c7f6}
.tab{display:none}.tab.active{display:block}
.status{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.status strong{font-size:26px;letter-spacing:-.6px}
.pill{border:1px solid #236688;border-radius:13px;background:#153b54;color:#58d4fc;padding:8px 12px;font-size:12px;white-space:nowrap}
code{font-size:13px;word-break:break-word}
#preview{border-radius:10px}
#previewEmpty{font-family:Inter,"Segoe UI",sans-serif}
#bboxsize{margin-top:8px}
@media(max-width:440px){main{padding:22px 13px 115px}h1{font-size:30px}header{align-items:flex-start}article{padding:18px;border-radius:19px}nav{bottom:9px}nav button{font-size:13px;padding:11px 6px}}
</style>
<main><header><div><div class="brand">LUMACUT / STUDIO</div><h1>Laser Studio</h1></div><span id="connection" class="pill">Verbinde …</span></header>
<div class="tab active" id="home">
<article><h2>Maschinenstatus</h2><div class="status"><strong id="state">Unbekannt</strong><span id="owner" class="hint">–</span></div><p class="hint" id="pos">X — · Y — · Z —</p><p class="hint" id="wifi"></p>
<div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-top:18px">
<svg viewBox="0 0 220 220" width="205" height="205" aria-label="Aktuelle Maschinenposition">
<rect x="10" y="10" width="200" height="200" rx="5" fill="#101d2e" stroke="#46718f" stroke-width="2"/>
<path d="M60 10V210 M110 10V210 M160 10V210 M10 60H210 M10 110H210 M10 160H210" stroke="#263a4d" stroke-width="1"/>
<circle id="machineSpot" cx="110" cy="110" r="8" fill="#ff304d" stroke="#ffffff" stroke-width="2" style="display:none"/>
</svg>
<div><strong style="font-size:17px">Live-Arbeitsfeld</strong>
<p id="machineSize" class="hint">Lese Verfahrweg...</p>
<p class="hint">Roter Punkt: aktuelle Position nach Referenzfahrt</p>
<p class="hint">Abmessungen werden aus GRBL $130/$131 gelesen.</p></div></div></article>
<article><h2>Aufträge</h2><div id="jobinfo" class="hint">Kein Job gewählt</div>
<div style="background:#101d2e;border:1px solid #35506b;border-radius:18px;padding:16px;margin:12px 0;text-align:center">
<svg id="preview" viewBox="0 0 300 138" width="100%" style="max-height:155px">
<rect x="8" y="8" width="284" height="122" rx="10" fill="#172638" stroke="#35506b" stroke-width="2"/>
<rect id="bbox" x="45" y="35" width="210" height="68" rx="2" fill="#153b54" stroke="#39c7f6" stroke-width="2" stroke-dasharray="7 4" style="display:none"/>
<text id="previewEmpty" x="150" y="75" text-anchor="middle" font-size="13" fill="#a4b4c7">Noch keine sichere Kontur</text>
</svg><div id="bboxsize" class="hint" style="font-size:13px">Konturabmessungen für unterstützten G-Code</div></div>
<div class="space"></div>
<div class="grid"><button onclick="act('frame')">Kontur testen</button><button class="blue" onclick="act('start')">Job starten</button><button onclick="act('pause')">Pause</button><button onclick="act('resume')">Fortsetzen</button><button class="red" onclick="act('abort')">Abbrechen</button><button onclick="act('park')">Parkposition</button></div>
<p class="hint">Maschinenaktionen verwenden den GRBL-Betriebszustand. Hardware-Not-Aus und Laserschutz bleiben unverändert. Die Laser-Vorschau mit 1 % ist nicht freigegeben.</p></article></div>
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
async function api(path,options){let opt=options||{};opt.headers=Object.assign({},opt.headers||{},{"X-LumaCut-Key":key});let response=await fetch(path,opt);if(!response.ok)throw Error((await response.text()).slice(0,200));return response.json()}
async function poll(){if(!key){msg('Zugangscode unter Gerät eingeben');return}try{
 const s=await api('/api/status');document.querySelector('#state').textContent=s.state||'?';
 document.querySelector('#owner').textContent=s.owner;document.querySelector('#pos').textContent=s.position;
 document.querySelector('#wifi').textContent=s.message||'';document.querySelector('#ip').textContent=location.host;
 const m=s.machine,pt=document.querySelector('#machineSpot');
 if(m&&m.work_area){
   const w=m.work_area.x_mm,h=m.work_area.y_mm,p=m.coordinates;
   document.querySelector('#machineSize').textContent=
     (w>0&&h>0)?w.toFixed(1)+' × '+h.toFixed(1)+' mm':'Arbeitsbereich noch nicht konfiguriert';
   if(p&&p.valid&&w>0&&h>0){
     const fx=p.zero_at_max?(p.x_mm+w)/w:p.x_mm/w;
     const fy=p.zero_at_max?(p.y_mm+h)/h:p.y_mm/h;
     if(fx>=0&&fx<=1&&fy>=0&&fy<=1){
       pt.setAttribute('cx',10+fx*200);pt.setAttribute('cy',10+(1-fy)*200);
       pt.style.display='';
     }else pt.style.display='none';
   }else pt.style.display='none';
 }else pt.style.display='none';
 document.querySelector('#jobinfo').textContent=s.job||'Kein Job gewählt';
 const box=document.querySelector('#bbox'), empty=document.querySelector('#previewEmpty');
 if(s.bounds&&Number.isFinite(s.bounds.x0)&&Number.isFinite(s.bounds.x1)&&
    Number.isFinite(s.bounds.y0)&&Number.isFinite(s.bounds.y1)){
    const width=Math.max(0,s.bounds.x1-s.bounds.x0),height=Math.max(0,s.bounds.y1-s.bounds.y0);
    const scale=Math.min(220/Math.max(width,.01),85/Math.max(height,.01));
    const pw=Math.max(2,width*scale),ph=Math.max(2,height*scale);
    box.setAttribute('x',150-pw/2);box.setAttribute('y',69-ph/2);
    box.setAttribute('width',pw);box.setAttribute('height',ph);
    box.style.display='';empty.style.display='none';
    document.querySelector('#bboxsize').textContent=width.toFixed(2)+' × '+height.toFixed(2)+' mm · Nur Begrenzung, keine Pfadvorschau';
 } else {
    box.style.display='none';empty.style.display='';
    document.querySelector('#bboxsize').textContent='G-Code-Geometrie nicht sicher ermittelbar – Framing gesperrt';
 }
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
