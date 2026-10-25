// LumaCut Pi 400 read-only machine monitor. Never sends motion/laser commands.
const tabs=document.querySelector(".aside .tabs");
const tab=document.createElement("button");tab.textContent="Maschine";tab.dataset.tab="machine";tab.type="button";tabs.append(tab);
tabs.style.gridTemplateColumns="repeat(4,minmax(0,1fr))";
const panel=document.createElement("div");panel.className="panel";panel.dataset.panel="machine";
panel.innerHTML=`<div class="gtitle">Raspberry Pi 400 · Marlin</div>
<p class="hint">Nur lesende Statusverbindung über die native Windows-Anwendung. LightBurn behält die Steuerung; es werden keine Motor- oder Laserbefehle gesendet.</p>
<label class="field">IP-Adresse des Pi<input id="piAddress" placeholder="192.168.x.x" autocomplete="off" inputmode="decimal"></label>
<button id="piReadStatus" class="full">Verbindung testen / Status lesen</button>
<p id="piConnectivity" class="hint" role="status">Nicht verbunden</p>
<div id="piDetails" class="group"></div>
<p class="hint">Homing, Laserstart und Job-Upload sind hier gesperrt, bis die reale Maschinenkalibrierung und Sicherheitsprüfung abgeschlossen sind.</p>`;
document.querySelector(".aside").append(panel);
tab.onclick=()=>{for(const t of document.querySelectorAll("[data-tab]"))t.classList.toggle("toolselected",t===tab);for(const p of document.querySelectorAll("[data-panel]"))p.classList.toggle("current",p===panel)};
const ip=document.getElementById("piAddress");
const info=document.getElementById("piConnectivity"),details=document.getElementById("piDetails");
ip.value=localStorage.getItem("lumacut.studio.pi.ip")||"";
const isLanIPv4=value=>{const match=/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(value.trim());if(!match)return false;const n=match.slice(1).map(Number);return n.every(v=>v>=0&&v<=255)&&((n[0]===10)||(n[0]===192&&n[1]===168)||(n[0]===172&&n[1]>=16&&n[1]<=31)||n[0]===127)};
function field(name,value){const row=document.createElement("div");row.className="stat";const key=document.createElement("span");key.textContent=name;const v=document.createElement("b");v.textContent=value===undefined||value===null?"—":String(value);row.append(key,v);details.append(row)}
let busy=false;
async function status(){
 if(busy)return;
 const addr=ip.value.trim();
 if(!isLanIPv4(addr)){info.textContent="Ungültige lokale IPv4-Adresse";return}
 if(typeof window.__TAURI__?.core?.invoke!=="function"){info.textContent="Status ist nur in der installierten Windows-Anwendung verfügbar.";return}
 busy=true;document.getElementById("piReadStatus").disabled=true;
 try{
  const data=await window.__TAURI__.core.invoke("read_pi_status",{host:addr});
  if(data.firmware!=="marlin")throw Error("Falsches Maschinenprofil");
  localStorage.setItem("lumacut.studio.pi.ip",addr);
  info.textContent="Pi erreichbar · Status zuletzt "+new Date().toLocaleTimeString("de-DE");
  details.replaceChildren();
  field("Firmware","Marlin");
  field("Controller",data.state);
  field("Maschine referenziert",data.homed?"Ja":"Nein");
  field("Konfiguration geprüft",data.validated?"Ja":"Nein");
  field("Schnittstelle belegt",data.owner);
  field("Position",Array.isArray(data.position)?data.position.join(" / ")+" mm":"—");
  field("Job",data.job?.state);
  field("Fortschritt",data.job?.total?Math.round(100*Number(data.job.line||0)/Number(data.job.total))+" %":"—");
  field("Störung",data.fault||"Keine gemeldet");
 }catch(error){info.textContent="Keine Statusverbindung: "+String(error).slice(0,240);details.replaceChildren()}
 finally{busy=false;document.getElementById("piReadStatus").disabled=false}
}
document.getElementById("piReadStatus").onclick=status;
setInterval(()=>{if(panel.classList.contains("current")&&details.children.length&&ip.value.trim())void status()},5000);
