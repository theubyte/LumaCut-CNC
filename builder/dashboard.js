(() => {
"use strict";
const $=id=>document.getElementById(id);
const TARGETS={
  complete:"lumacut_complete_suite_unverified",
  hmi:"esp32_hmi_pro_unverified",
  skr:"stm32_hmi_bridge_unverified"
};
const NAMES={
  lumacut_complete_suite_unverified:"Komplett · HMI + grblHAL",
  esp32_hmi_pro_unverified:"Waveshare HMI · Control OS",
  stm32_hmi_bridge_unverified:"Laser grblHAL · SKR UART",
  stm32_project_unverified:"SKR USB · Legacy",
  esp32_hmi_unverified:"HMI Display · Diagnose",
  esp32_hmi_keypad_unverified:"HMI UART · Test",
  tests:"Projekt-Tests"
};
const model={
  jobs:[], active:null, selected:null, watch:new Set(), notified:new Set(),
  initialized:false, refreshing:false, terminalText:"", localLines:[],
  logId:null, logValue:"", logBusy:false, modalContext:null
};
const escapeHtml=s=>String(s??"").replace(/[&<>"']/g,c=>({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
})[c]);
const label=j=>NAMES[j.target]||j.target||"Unbekannter Build";
const isHmi=j=>!!j&&["esp32_hmi_pro_unverified","esp32_hmi_unverified",
  "esp32_hmi_keypad_unverified","lumacut_complete_suite_unverified"].includes(j.target);
const isSkr=j=>!!j&&["stm32_project_unverified","stm32_hmi_bridge_unverified",
  "lumacut_complete_suite_unverified"].includes(j.target);
const duration=n=>{
  if(n===undefined||n===null||!Number.isFinite(Number(n)))return "–";
  n=Math.max(0,Math.round(Number(n)));
  const h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;
  return h?(h+"h "+String(m).padStart(2,"0")+"m"):
    (m?m+"m "+String(s).padStart(2,"0")+"s":s+"s");
};
const api=async(url,options)=>{
  const r=await fetch(url,{cache:"no-store",...options});
  if(!r.ok){
    let msg="HTTP "+r.status;
    try{const data=await r.json();msg=data.error||data.message||msg;}catch(_){}
    throw Error(msg);
  }
  return r;
};
const artifact=(j,name)=>"/artifacts/"+encodeURIComponent(j.id)+"/"+encodeURIComponent(name);
const sdUrl=j=>"/api/jobs/"+encodeURIComponent(j.id)+"/sd-image";
function toast(message,error=false){
  const el=$("toast");el.textContent=message;el.classList.toggle("error",error);
  el.classList.add("visible");
  clearTimeout(toast.timeout);toast.timeout=setTimeout(()=>el.classList.remove("visible"),5200);
}
function statusText(status){
  return status==="success"?"ERFOLGREICH":status==="running"?"LÄUFT":
    status==="failed"?"FEHLGESCHLAGEN":"BEREIT";
}
function find(id){return model.jobs.find(x=>x.id===id);}
function latest(predicate){return model.jobs.find(j=>j.status==="success"&&predicate(j));}
function setConnection(ok){
  for(const id of ["health-led","top-led"]){
    $(id).classList.toggle("connected",ok);
    $(id).classList.toggle("error",!ok);
  }
  $("connection-text").textContent=ok?"Buildserver verbunden":"Buildserver nicht erreichbar";
  $("top-state").textContent=ok?"System online":"Verbindung fehlt";
}
function renderActivity(){
  const j=find(model.active)||find(model.selected);
  const buttons=document.querySelectorAll("[data-action=complete],[data-action=hmi],[data-action=skr]");
  buttons.forEach(b=>b.disabled=!!model.active);
  $("active-log-button").disabled=!j;
  if(!j){
    $("active-title").textContent="Bereit für deinen nächsten Build";
    $("active-description").textContent="Wähle oben eine Aktion, um zu beginnen.";
    $("active-status").textContent="BEREIT";$("active-status").className="state-chip";
    $("progress-fill").style.width="0%";$("progress-value").textContent="0%";
    $("progress-stage").textContent="–";$("progress-time").textContent="–";
    $("progress-elapsed").textContent="–";
    $("commit-line").textContent="GitHub-Stand wird beim Build ermittelt.";
    return;
  }
  const p=j.status==="success"?100:(j.progress_pct||0);
  $("active-title").textContent=label(j);
  $("active-description").textContent=j.status==="running"?
    "Build läuft auf deinem Unraid-Server. Live-Status wird fortlaufend aktualisiert.":
    (j.status==="success"?"Build ist fertig. Die Firmware-Dateien sind im Archiv verfügbar.":
     "Dieser Build ist fehlgeschlagen. Öffne das Terminal für den genauen Fehler.");
  $("active-status").textContent=statusText(j.status);
  $("active-status").className="state-chip "+j.status;
  $("progress-fill").style.width=p+"%";
  $("progress-value").textContent=p+"%";
  $("progress-stage").textContent=j.stage||statusText(j.status);
  $("progress-time").textContent=j.status==="running"?
    ("ca. "+duration(j.eta_seconds)):("–");
  $("progress-elapsed").textContent=duration(j.elapsed_seconds);
  $("commit-line").textContent="SOURCE: "+(j.source_sha?j.source_sha.slice(0,12):
    "GitHub-Commit wird ermittelt");
}
function renderHistory(){
  const val=$("history-search").value.trim().toLowerCase();
  const filter=$("history-filter").value;
  const jobs=model.jobs.filter(j=>(filter==="all"||j.status===filter)&&
    (!val||(label(j)+" "+j.target+" "+j.id+" "+(j.source_sha||"")).toLowerCase().includes(val)));
  $("history-count").textContent=model.jobs.length;
  $("nav-count").textContent=model.jobs.length;
  const el=$("history-list");
  if(!jobs.length){el.innerHTML='<div class="empty-state">Keine passenden Builds gefunden.</div>';return;}
  el.innerHTML=jobs.map(j=>{
    const t=j.created_utc?new Date(j.created_utc).toLocaleString("de-DE",
      {day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}):"–";
    return '<button class="history-item'+(model.selected===j.id?" selected":"")+
      '" data-job="'+escapeHtml(j.id)+'" aria-label="Build '+escapeHtml(j.id)+' wählen">'+
      '<span><span class="record-name">'+escapeHtml(label(j))+'</span>'+
      '<span class="record-meta">'+escapeHtml(t)+' · '+escapeHtml((j.source_sha||j.id).slice(0,12))+
      '</span></span><span class="history-badge '+escapeHtml(j.status)+'">'+
      escapeHtml(statusText(j.status))+'</span></button>';
  }).join("");
  el.querySelectorAll("[data-job]").forEach(button=>{
    button.addEventListener("click",()=>selectJob(button.dataset.job));
  });
}
function renderDetails(){
  const j=find(model.selected);
  $("details-empty").hidden=!!j;$("details-content").hidden=!j;
  if(!j){$("detail-chip").textContent="KEINE AUSWAHL";return;}
  $("detail-chip").textContent=statusText(j.status);
  $("detail-chip").className="small-state "+j.status;
  $("detail-target").textContent=label(j);
  $("detail-sha").textContent=j.source_sha?j.source_sha.slice(0,16):"–";
  $("detail-duration").textContent=duration(j.elapsed_seconds);
  $("detail-state").textContent=statusText(j.status);
  $("detail-zip").href=artifact(j,"build-package.zip");
  const pair=(j.status==="success"&&j.paired_firmware);
  const ready=(pair&&j.release_ready===true);
  $("approve-update").hidden=!pair;
  $("approve-update").textContent=ready?
    "Als Update für das HMI freigeben":"Neues OTA-fähiges Komplett-Build starten";
  $("release-hint").hidden=!pair||ready;
  $("release-hint").textContent=!ready&&pair?
    (j.release_blocker||"Dieses Build ist nicht als OTA-Update freigabefaehig."): "";
  const files=j.files||[];
  $("artifact-list").innerHTML=files.length?files.map(f=>{
    const sha=f.sha256||"";
    const bytes=Number(f.bytes||0),size=bytes>=1048576?
      (bytes/1048576).toFixed(1)+" MB":(bytes/1024).toFixed(0)+" KB";
    return '<div class="artifact-file"><div><b>'+escapeHtml(f.name)+'</b>'+
      '<small>'+escapeHtml(size)+' · SHA256 '+escapeHtml(sha.slice(0,16))+'…</small></div>'+
      '<a href="'+artifact(j,f.name)+'" title="Datei herunterladen" download>↓</a></div>';
  }).join(""):'<div class="empty-state">Noch keine Artefakte vorhanden.</div>';
}
function selectJob(id){
  if(!find(id))return;
  model.selected=id;
  renderHistory();renderDetails();renderActivity();
  $("download-log").href=artifact(find(id),"build.log");
  pollLog(true);
}
function addLocal(text){
  model.localLines.push(text);
  if(model.localLines.length>65)model.localLines.splice(0,model.localLines.length-65);
  renderTerminal();
}
function renderTerminal(){
  const output=$("terminal-output");
  const t=(model.logValue||"")+(model.localLines.length?
    "\n\n"+model.localLines.join("\n"):"");
  if(t===model.terminalText)return;
  model.terminalText=t;
  output.textContent=t||"$ LumaCut Build Lab bereit.\n  Tippe help für Kommandos.";
  if($("autoscroll").checked)output.scrollTop=output.scrollHeight;
}
async function pollLog(force=false){
  const id=model.selected||model.active;
  if(!id||model.logBusy)return;
  if(!force&&id!==model.logId){model.logValue="";model.terminalText="";}
  model.logBusy=true;
  try{
    const r=await api("/api/jobs/"+encodeURIComponent(id)+"/log");
    const text=await r.text();
    if(id!==model.logId||text!==model.logValue){
      model.logId=id;model.logValue=text;renderTerminal();
    }
  }catch(e){
    if(force)addLocal("Log noch nicht verfügbar: "+e.message);
  }finally{model.logBusy=false;}
}
let releaseLastCheck=0;
async function refreshApprovedRelease(){
  const now=Date.now();
  if(now-releaseLastCheck<15000)return;
  releaseLastCheck=now;
  try{
    const r=await api("/api/updates/latest");
    const m=await r.json();
    $("stable-release").textContent=m.available&&m.source_sha?
      "STABLE: "+m.source_sha.slice(0,12):"STABLE: Noch nicht veröffentlicht";
  }catch(_){
    $("stable-release").textContent="STABLE: Nicht erreichbar";
  }
}
async function refresh(){
  if(model.refreshing)return;
  model.refreshing=true;
  try{
    const r=await api("/api/jobs");
    const data=await r.json();
    setConnection(true);
    await refreshApprovedRelease();
    model.jobs=data.jobs||[];
    const prior=model.active;
    model.active=data.active||null;
    if(!model.initialized){
      if(model.active){model.watch.add(model.active);model.selected=model.active;}
      else if(model.jobs.length)model.selected=model.jobs[0].id;
      model.initialized=true;
    }
    if(model.active&&model.active!==prior){
      model.watch.add(model.active);model.selected=model.active;
    }
    if(model.selected&&!find(model.selected)&&model.selected!==model.active)
      model.selected=model.jobs[0]?.id||null;
    for(const id of [...model.watch]){
      const job=find(id);
      if(job&&job.status!=="running"&&!model.notified.has(id)){
        model.notified.add(id);model.watch.delete(id);showFinish(job);
      }
    }
    renderActivity();renderHistory();renderDetails();
    if(model.selected)await pollLog();
  }catch(e){setConnection(false);if(!model.initialized)toast(e.message,true);}
  finally{model.refreshing=false;}
}
async function build(target){
  if(model.active){toast("Es läuft bereits ein Build.",true);return;}
  closeModal();
  try{
    const r=await api("/api/build",{method:"POST",headers:{
      "Content-Type":"application/json","X-LumaCut-Action":"build"},
      body:JSON.stringify({target})});
    const result=await r.json();
    model.active=result.id;model.selected=result.id;
    model.watch.add(result.id);
    model.logId=null;model.logValue="";model.localLines=[];
    addLocal("$ Build angefordert: "+(NAMES[target]||target));
    toast("Build gestartet.");
    await refresh();
    $("overview").scrollIntoView({behavior:"smooth"});
  }catch(e){toast("Build konnte nicht gestartet werden: "+e.message,true);}
}
function openModal(title,description,opts={}){
  $("modal-root").hidden=false;
  $("modal-title").textContent=title;
  $("modal-description").textContent=description;
  $("modal-kicker").textContent=opts.kicker||"LUMACUT / ACTION";
  $("modal-icon").textContent=opts.icon||"✓";
  $("modal-icon").className="modal-icon "+(opts.error?"failed":"");
  $("modal-meta").textContent=opts.meta||"LumaCut Studio · Build Lab";
  $("modal-actions").replaceChildren();
  $("modal-flash").hidden=true;$("modal-flash").replaceChildren();
  document.body.style.overflow="hidden";
  $("modal-close").focus();
}
function closeModal(){
  $("modal-root").hidden=true;
  document.body.style.overflow="";
  model.modalContext=null;
}
function modalButton(title,fn,alt=false){
  const b=document.createElement("button");b.className="modal-button"+(alt?" alt":"");
  b.type="button";b.textContent=title;
  b.addEventListener("click",fn);$("modal-actions").appendChild(b);
  return b;
}
function modalLink(title,href,alt=false){
  const a=document.createElement("a");
  a.className="modal-button"+(alt?" alt":"");a.textContent=title;
  a.href=href;a.download="";$("modal-actions").appendChild(a);
}
function showFinish(j){
  const ok=j.status==="success";
  openModal(ok?"Build erfolgreich abgeschlossen":"Build fehlgeschlagen",
    ok?label(j)+" wurde aus Commit "+(j.source_sha||"").slice(0,12)+
      " erstellt. Was möchtest du damit machen?":
      "Beim Build von "+label(j)+" ist ein Fehler aufgetreten. Das vollständige Log ist gespeichert.",
    {kicker:ok?"BUILD COMPLETED":"BUILD FAILED",icon:ok?"✓":"!",
      meta:"Build "+j.id+" · "+duration(j.elapsed_seconds),error:!ok});
  model.modalContext=j.id;
  if(ok){
    if(j.paired_firmware)modalLink("Gesamtes Firmware-Paket herunterladen ↓",
      artifact(j,"LumaCut-Control-OS-Komplettpaket.zip"));
    if(isHmi(j))modalButton("Waveshare HMI flashen ↗",()=>showFlash(j),true);
    if(isSkr(j))modalButton("grblHAL als firmware.bin auf SD speichern",()=>showSd(j),true);
    if(isHmi(j))modalLink("Windows-HMI-Flashpaket herunterladen",
      artifact(j,"Waveshare-HMI-Flash-Paket-Windows.zip"),true);
    if(!j.paired_firmware)modalLink("Build-ZIP herunterladen ↓",
      artifact(j,"build-package.zip"),true);
  }else{
    modalButton("Fehlerprotokoll öffnen",()=>{closeModal();selectJob(j.id);
      $("terminal-section").scrollIntoView({behavior:"smooth"});});
    modalButton("Build erneut starten",()=>build(j.target),true);
  }
  modalButton("Log ansehen",()=>{closeModal();selectJob(j.id);
    $("terminal-section").scrollIntoView({behavior:"smooth"});},true);
}
async function approveRelease(){
  const j=find(model.selected);
  if(!j||j.status!=="success"||!j.paired_firmware)return;
  if(j.release_ready!==true){
    // Older paired build archives lack the app-only HMI OTA image.
    // Never publish a merged bootloader image as an OTA application.
    await build(TARGETS.complete);
    return;
  }
  if(!window.confirm(
    "Dieses HMI-/SKR-Paket als STABLE-Update freigeben?\\n"+
    "Beide Firmwaredateien werden veroeffentlicht. Die Installation startet nicht von selbst."))return;
  try{
    const response=await api("/api/updates/approve",{
      method:"POST",
      headers:{"Content-Type":"application/json","X-LumaCut-Action":"build"},
      body:JSON.stringify({job_id:j.id})});
    const data=await response.json();
    toast("Update-Kanal freigegeben: "+data.source_sha.slice(0,12));
    openModal("HMI- und SKR-Update veröffentlicht",
      "Beide Firmwaredateien sind als gemeinsamer Stand freigegeben. "+
      "HMI: Update im Systemmenue pruefen und installieren. "+
      "SKR: Passende firmware.bin hier herunterladen und ueber den "+
      "vorhandenen microSD-Bootloader des Boards installieren.",
      {kicker:"STABLE RELEASE",icon:"✓",meta:data.source_sha.slice(0,12)});
    modalLink("SKR-Update firmware.bin herunterladen",
      "/api/updates/skr-firmware.bin",true);
    modalLink("Update-Manifest prüfen", "/api/updates/latest");
  }catch(e){toast("Freigabe fehlgeschlagen: "+e.message,true);}
}
function showFlash(job){
  const j=job||latest(isHmi);
  if(!j){
    openModal("Kein HMI-Build vorhanden",
      "Für das Waveshare ESP32-S3 wird zuerst ein erfolgreicher HMI-Build benötigt.",
      {icon:"▣",kicker:"HMI / FLASH"});
    modalButton("Build HMI starten",()=>build(TARGETS.hmi));
    return;
  }
  openModal("Waveshare HMI flashen",
    "Waveshare ESP32-S3-Touch-LCD-7 Rev1.2 über den USB-TO-UART-Anschluss am PC anschließen. USB-Schalter auf UART1. Laser physisch stromlos.",
    {icon:"↯",kicker:"DEVICE / FLASH",meta:"Quell-Commit: "+
      (j.source_sha||"").slice(0,12)+" · "+j.id});
  model.modalContext=j.id;
  if(window.isSecureContext&&"serial" in navigator){
    modalButton("Browser-Flasher öffnen (HTTPS)",()=>{
      const panel=$("modal-flash");
      panel.hidden=false;panel.replaceChildren();
      const p=document.createElement("p");
      p.textContent="Im Browser den Waveshare-COM-Port auswählen und die USB-Bestätigung abwarten.";
      panel.appendChild(p);
      const installer=document.createElement("esp-web-install-button");
      installer.setAttribute("manifest","/api/jobs/"+encodeURIComponent(j.id)+
        "/flash-manifest.json");
      panel.appendChild(installer);
    });
  }else{
    const small=document.createElement("div");
    small.className="terminal-disclaimer";
    small.textContent="Direkter Browser-USB-Zugriff erfordert HTTPS oder localhost in Chrome/Edge. "+
      "Im normalen Unraid-HTTP-LAN bitte das Windows-Flashpaket verwenden.";
    $("modal-actions").appendChild(small);
  }
  modalLink("Windows-Flashpaket herunterladen ↓",
    artifact(j,"Waveshare-HMI-Flash-Paket-Windows.zip"),true);
  modalLink("ESP32-S3-Firmware-BIN herunterladen",
    artifact(j,"LUMACUT_HMI_ESP32S3_MERGED.bin"),true);
  modalButton("Build-Log ansehen",()=>{closeModal();selectJob(j.id);
    $("terminal-section").scrollIntoView({behavior:"smooth"});},true);
}
async function saveOnSd(job){
  const url=sdUrl(job);
  if(!(window.isSecureContext&&window.showDirectoryPicker)){
    window.location.assign(url);
    toast("firmware.bin wird heruntergeladen. Als Ziel das Stammverzeichnis der microSD wählen.");
    return;
  }
  try{
    const dir=await window.showDirectoryPicker({mode:"readwrite"});
    // Avoid silent overwrite of an existing firmware.bin.
    try{
      await dir.getFileHandle("firmware.bin",{create:false});
      if(!window.confirm("firmware.bin ist bereits vorhanden. Überschreiben?"))return;
    }catch(e){if(e.name!=="NotFoundError")throw e;}
    const response=await api(url),blob=await response.blob();
    const f=await dir.getFileHandle("firmware.bin",{create:true});
    const stream=await f.createWritable();
    await stream.write(blob);await stream.close();
    toast("firmware.bin gespeichert. Vor dem Einstecken SKR-Bootloader und Board prüfen.");
    closeModal();
  }catch(e){
    if(e.name!=="AbortError")toast("SD-Speichern fehlgeschlagen: "+e.message,true);
  }
}
function showSd(job){
  const j=job||latest(isSkr);
  if(!j){
    openModal("Noch keine SKR-Firmware",
      "Bitte zuerst den grblHAL-Build durchführen, dann steht firmware.bin bereit.",
      {icon:"▤",kicker:"STORAGE / MICROSD"});
    modalButton("Build Laser grblHAL starten",()=>build(TARGETS.skr));
    return;
  }
  openModal("grblHAL auf SD-Karte speichern",
    "Das Build Lab erstellt die Datei firmware.bin für das SKR Mini MZ. "+
    "Speichere sie im Stammverzeichnis einer geeigneten microSD-Karte. "+
    "Das Kopieren flasht das Board nicht automatisch; der Bootloader muss es unterstützen.",
    {icon:"▤",kicker:"FIRMWARE / MICROSD",
      meta:"Quelle: "+(j.source_sha||"").slice(0,12)+" · "+j.id});
  model.modalContext=j.id;
  if(window.isSecureContext&&window.showDirectoryPicker)
    modalButton("SD-Karten-Ordner auswählen und speichern",()=>saveOnSd(j));
  modalLink("firmware.bin herunterladen ↓",sdUrl(j),
    !!(window.isSecureContext&&window.showDirectoryPicker));
  modalButton("Build-Log ansehen",()=>{closeModal();selectJob(j.id);
    $("terminal-section").scrollIntoView({behavior:"smooth"});},true);
}
async function terminalCommand(cmd){
  const args=cmd.trim().split(/\s+/);const head=args[0]?.toLowerCase();
  if(!head)return;
  const j=find(model.selected)||find(model.active)||model.jobs[0];
  if(head==="clear"){model.localLines=[];model.logValue="";
    model.terminalText="";renderTerminal();return;}
  addLocal("$ "+cmd);
  if(head==="help")addLocal(
    "Befehle: help, status, jobs, log [id], files, manifest, source, refresh, clear\n"+
    "Sicherheitsmodus: Nur lesende Build- und Protokollfunktionen.");
  else if(head==="status")addLocal(model.active?
    "LÄUFT: "+label(find(model.active)||{})+" / "+(find(model.active)?.stage||"")+
      " / "+(find(model.active)?.progress_pct||0)+"%":
    "Kein aktiver Build. Letzter Build: "+(model.jobs[0]?label(model.jobs[0]):"–"));
  else if(head==="jobs")addLocal(model.jobs.slice(0,12).map(j=>j.id+"  "+
    j.status.padEnd(8," ")+"  "+label(j)).join("\n")||"Keine Builds.");
  else if(head==="log"){
    const id=args[1]||j?.id;
    if(!id||!find(id)){addLocal("Build nicht gefunden.");return;}
    selectJob(id);addLocal("Protokoll geladen: "+id);
  }else if(head==="files")addLocal(j?
    (j.files||[]).map(f=>f.name+"  "+f.bytes+" bytes").join("\n")||"Noch keine Artefakte.":
    "Kein Build ausgewählt.");
  else if(head==="manifest")addLocal(j?"Manifest: "+artifact(j,"manifest.json"):
    "Kein Build ausgewählt.");
  else if(head==="source")addLocal(j?
    "Repository: "+j.repository+"\nBranch: "+j.branch+
      "\nCommit: "+(j.source_sha||"noch unbekannt"):
    "Kein Build ausgewählt.");
  else if(head==="refresh"){await refresh();addLocal("Status aktualisiert.");}
  else addLocal("Unbekannter Befehl. Tippe help. Kein Remote-Shell-Zugriff.");
}
function init(){
  document.querySelectorAll("[data-action]").forEach(button=>
    button.addEventListener("click",()=>{
      const act=button.dataset.action;
      if(TARGETS[act])build(TARGETS[act]);
      else if(act==="flash")showFlash();
      else if(act==="sd")showSd();
    }));
  $("history-search").addEventListener("input",renderHistory);
  $("history-filter").addEventListener("change",renderHistory);
  $("refresh-button").addEventListener("click",refresh);
  $("active-log-button").addEventListener("click",()=>{
    const j=find(model.active)||find(model.selected);if(!j)return;
    selectJob(j.id);$("terminal-section").scrollIntoView({behavior:"smooth"});
  });
  $("approve-update").addEventListener("click",approveRelease);
  $("detail-log").addEventListener("click",()=>{
    $("terminal-section").scrollIntoView({behavior:"smooth"});pollLog(true);
  });
  $("copy-terminal").addEventListener("click",async()=>{
    try{await navigator.clipboard.writeText($("terminal-output").textContent);
      toast("Terminaltext kopiert.");}catch(e){toast("Kopieren nicht erlaubt.",true);}
  });
  $("clear-terminal").addEventListener("click",()=>{
    model.logValue="";model.localLines=[];model.terminalText="";
    $("terminal-output").textContent="Anzeige geleert. Live-Log beim nächsten Aktualisieren wieder sichtbar.";
  });
  $("terminal-form").addEventListener("submit",e=>{
    e.preventDefault();const field=$("terminal-command");const cmd=field.value;
    field.value="";terminalCommand(cmd);
  });
  $("modal-close").addEventListener("click",closeModal);
  $("modal-dismiss").addEventListener("click",closeModal);
  $("modal-root").addEventListener("click",e=>{
    if(e.target===$("modal-root"))closeModal();
  });
  document.addEventListener("keydown",e=>{
    if(e.key==="Escape"&&!$("modal-root").hidden)closeModal();
  });
  const updateClock=()=>{$("clock").textContent=new Date().toLocaleString("de-DE",
    {hour:"2-digit",minute:"2-digit"})};
  updateClock();setInterval(updateClock,30000);
  refresh();setInterval(refresh,2200);
}
document.addEventListener("DOMContentLoaded",init);
})();