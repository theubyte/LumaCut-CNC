// LumaCut Pi 400 machine panel: status plus control through the Pi web API.
// Studio only requests actions; homing order, 30 mm safe zone, Z floor,
// G30 evaluation, focus and laser interlocks are enforced on the Pi.
const tabs=document.querySelector(".aside .tabs");
const tab=document.createElement("button");tab.textContent="Maschine";tab.dataset.tab="machine";tab.type="button";tabs.append(tab);
tabs.style.gridTemplateColumns="repeat(4,minmax(0,1fr))";
const panel=document.createElement("div");panel.className="panel";panel.dataset.panel="machine";
panel.innerHTML=`<div class="gtitle">Raspberry Pi 400 · Marlin</div>
<p class="hint">Steuerung über die Pi-API (Port 8080). Ist LightBurn verbunden, lehnt der Pi Befehle von hier ab, bis LightBurn getrennt ist.</p>
<label class="field">IP-Adresse des Pi<input id="piAddress" placeholder="192.168.x.x" autocomplete="off" inputmode="decimal"></label>
<button id="piReadStatus" class="full">Verbindung testen / Status lesen</button>
<p id="piConnectivity" class="hint" role="status">Nicht verbunden</p>
<div id="piDetails" class="group"></div>
<div class="gtitle">Ablauf</div>
<button class="full primary" data-pi-op="send-autorun">Projekt senden &amp; Ein-Klick-Start</button>
<p class="hint">Homing X/Y → Z → Rückzug, Abtasten (G30) unter der Motivmitte, Fokus, Auftrag, Parken auf X0/Y0. Unter der Motivmitte muss Material liegen.</p>
<div class="actions" style="display:grid;grid-template-columns:1fr 1fr">
<button data-pi-op="home">Referenzieren</button><button data-pi-op="probe">Abtasten (G30)</button>
<button data-pi-op="send">Nur senden</button><button data-pi-op="abort">Auftrag abbrechen</button>
<button data-pi-op="light">Licht</button><button data-pi-op="exhaust">Abluft</button>
</div>
<div class="gtitle">Joggen</div>
<label class="field">Schrittweite<select id="piStep"><option value="0.1">0,1 mm</option><option value="1" selected>1 mm</option><option value="10">10 mm</option></select></label>
<div class="actions" style="display:grid;grid-template-columns:repeat(3,1fr)">
<button data-pi-jog="Y" data-dir="1">Y +</button><button data-pi-jog="X" data-dir="-1">X −</button><button data-pi-jog="Z" data-dir="1">Z +</button>
<button data-pi-jog="Y" data-dir="-1">Y −</button><button data-pi-jog="X" data-dir="1">X +</button><button data-pi-jog="Z" data-dir="-1">Z −</button>
</div>
<button class="full" data-pi-op="estop" style="border-color:#c0504d;color:#ff9b96">Software-Notstopp M112</button>`;
document.querySelector(".aside").append(panel);
tab.onclick=()=>{for(const t of document.querySelectorAll("[data-tab]"))t.classList.toggle("toolselected",t===tab);for(const p of document.querySelectorAll("[data-panel]"))p.classList.toggle("current",p===panel)};
const ip=document.getElementById("piAddress");
const info=document.getElementById("piConnectivity"),details=document.getElementById("piDetails");
ip.value=localStorage.getItem("lumacut.studio.pi.ip")||"";
const isLanIPv4=value=>{const match=/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(value.trim());if(!match)return false;const n=match.slice(1).map(Number);return n.every(v=>v>=0&&v<=255)&&((n[0]===10)||(n[0]===192&&n[1]===168)||(n[0]===172&&n[1]>=16&&n[1]<=31)||n[0]===127)};
function field(name,value){const row=document.createElement("div");row.className="stat";const key=document.createElement("span");key.textContent=name;const v=document.createElement("b");v.textContent=value===undefined||value===null?"—":String(value);row.append(key,v);details.append(row)}
const mm=v=>typeof v==="number"?v.toFixed(2)+" mm":"—";
let busy=false,last=null;
function host(){
 const addr=ip.value.trim();
 if(!isLanIPv4(addr))throw Error("Ungültige lokale IPv4-Adresse");
 if(typeof window.__TAURI__?.core?.invoke!=="function")throw Error("Maschinensteuerung ist nur in der installierten Windows-Anwendung verfügbar.");
 return addr;
}
async function status(){
 if(busy)return;
 let addr;
 try{addr=host()}catch(error){info.textContent=error.message;return}
 busy=true;document.getElementById("piReadStatus").disabled=true;
 try{
  const data=await window.__TAURI__.core.invoke("read_pi_status",{host:addr});
  if(data.firmware!=="marlin")throw Error("Falsches Maschinenprofil");
  last=data;
  localStorage.setItem("lumacut.studio.pi.ip",addr);
  info.textContent="Pi erreichbar · Status zuletzt "+new Date().toLocaleTimeString("de-DE");
  details.replaceChildren();
  field("Controller",data.connected===false?"SKR getrennt":data.state);
  field("Maschine referenziert",data.homed?"Ja":"Nein");
  field("Konfiguration geprüft",data.validated?"Ja":"Nein");
  field("Schnittstelle belegt",data.owner);
  field("Position",Array.isArray(data.position)?data.position.map(v=>Number(v).toFixed(2)).join(" / ")+" mm":"—");
  field("Werkstück Z / Fokus Z",data.workpiece_surface_z==null?"Nicht abgetastet":mm(data.workpiece_surface_z)+" / "+mm(data.laser_focus_z));
  field("Job",data.job?.state);
  field("Fortschritt",data.job?.total?Math.round(100*Number(data.job.line||0)/Number(data.job.total))+" %":"—");
  field("Störung",data.emergency_latched?"M112 verriegelt – Dienst neu starten":(data.job?.error||data.fault||"Keine gemeldet"));
 }catch(error){info.textContent="Keine Statusverbindung: "+String(error).slice(0,240);details.replaceChildren()}
 finally{busy=false;document.getElementById("piReadStatus").disabled=false}
}
async function action(op,fields={}){
 return window.__TAURI__.core.invoke("pi_action",{host:host(),op,fields});
}
async function sendProject(){
 if(typeof window.lumacutStudio?.marlinJob!=="function")throw Error("Projekt-Export nicht geladen");
 const gcode=await window.lumacutStudio.marlinJob();
 const name="studio-"+new Date().toISOString().replace(/[^0-9]/g,"").slice(0,14)+".gcode";
 const result=await window.__TAURI__.core.invoke("pi_upload_job",{host:host(),filename:name,gcode});
 return {name,message:result.message};
}
async function run(button,task){
 for(const b of panel.querySelectorAll("[data-pi-op],[data-pi-jog]"))b.disabled=true;
 try{info.textContent=await task()||"Bestätigt"}
 catch(error){info.textContent="Abgelehnt: "+String(error?.message||error).slice(0,300)}
 finally{for(const b of panel.querySelectorAll("[data-pi-op],[data-pi-jog]"))b.disabled=false;void status()}
}
for(const button of panel.querySelectorAll("[data-pi-op]"))button.onclick=()=>run(button,async()=>{
 const op=button.dataset.piOp;
 if(op==="estop"){if(!confirm("Marlin-Notstopp M112 auslösen? Danach SKR prüfen und Pi-Dienst neu starten."))return "Kein Notstopp ausgelöst";return (await action("estop")).message}
 if(op==="send")return (await sendProject()).message;
 if(op==="send-autorun"){
  if(!confirm("Maschine fährt Homing, tastet unter der Motivmitte ab und lasert den Auftrag. Bereich frei und Material eingelegt?"))return "Nicht gestartet";
  const sent=await sendProject();
  return (await action("autorun",{name:sent.name})).message;
 }
 if(op==="light")return (await action("light",{on:last?.lights?"0":"1"})).message;
 if(op==="exhaust")return (await action("exhaust",{on:last?.exhaust?"0":"1"})).message;
 return (await action(op)).message;
});
for(const button of panel.querySelectorAll("[data-pi-jog]"))button.onclick=()=>run(button,async()=>{
 const distance=Number(document.getElementById("piStep").value)*Number(button.dataset.dir);
 return (await action("jog",{axis:button.dataset.piJog,distance:String(distance)})).message;
});
document.getElementById("piReadStatus").onclick=status;
setInterval(()=>{if(panel.classList.contains("current")&&details.children.length&&ip.value.trim())void status()},3000);
