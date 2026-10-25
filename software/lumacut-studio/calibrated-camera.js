import {buildCameraCalibration,verifyCalibration,rectifyArea} from "./camera-calibration-core.mjs";
const $=id=>document.getElementById(id);
const panel=document.querySelector('[data-panel="camera"]');
const section=document.createElement("section");section.className="group";
section.innerHTML=`
<div class="gtitle">Kamera geometrisch kalibrieren</div>
<p class="hint">5 Messmarkierungen mit bekannten Maschinenpositionen auf einem Kalibrierbrett platzieren. Danach die Punkte nacheinander im Livebild anklicken. Die fünfte Markierung ist eine unabhängige Genauigkeitsprüfung. Die Software bewegt hierbei keinen Motor.</p>
<div id="fiducialCoordinates"></div>
<button id="startFiducials" class="full">5 Referenzmarkierungen erfassen</button>
<p id="calibrationStatus" class="hint" role="status">Nicht kalibriert. Maßhaltige Ausschnitte gesperrt.</p>
<button id="resetFiducials">Kalibrierung zurücksetzen</button>
`;
panel.append(section);
const defaults=[[40,40],[340,40],[340,340],[40,340],[190,190]];
const labels=["Oben links","Oben rechts","Unten rechts","Unten links","Prüfpunkt"];
const coords=$("fiducialCoordinates");
defaults.forEach((p,i)=>{const div=document.createElement("div");div.className="field";const label=document.createElement("label");label.textContent=labels[i]+" (X / Y mm)";const group=document.createElement("div");group.style.cssText="display:flex;gap:6px";
for(let j=0;j<2;j++){const input=document.createElement("input");input.type="number";input.step=".1";input.min=j===0?"0":"30";input.max=j===0?"390":"370";input.value=p[j];input.id="fid"+i+j;input.style.width="50%";group.append(input)}
div.append(label,group);coords.append(div)});
let selected=[],calibration=null,phase="idle",videoW=0,videoH=0;
function toast(msg){const el=$("calibrationStatus");el.textContent=msg}
function refs(){return defaults.map((_,i)=>[Number($("fid"+i+"0").value),Number($("fid"+i+"1").value)])}
function verifyRefs(pp){const coords=refs();for(const [x,y] of coords){if(!Number.isFinite(x)||!Number.isFinite(y)||x<0||y<30||x>390||y>370)throw Error("Markierung liegt außerhalb des Arbeitsbereichs")}return coords}
$("startFiducials").onclick=()=>{const v=$("cameraView");if(!v.videoWidth)return toast("Zuerst Kamera einschalten.");try{verifyRefs()}catch(e){return toast(e.message)}selected=[];calibration=null;phase="capture";videoW=v.videoWidth;videoH=v.videoHeight;toast("Punkt 1/5: "+labels[0]+" im Videobild anklicken.")};
const video=$("cameraView");
video.style.cursor="crosshair";
video.addEventListener("click",e=>{
 if(phase!=="capture")return;
 if(video.videoWidth!==videoW||video.videoHeight!==videoH){phase="idle";return toast("Kameraauflösung geändert. Erfassung neu starten.")}
 const r=video.getBoundingClientRect();
 const scale=Math.min(r.width/video.videoWidth,r.height/video.videoHeight);
 const visibleW=video.videoWidth*scale,visibleH=video.videoHeight*scale;
 const sx=(r.width-visibleW)/2,sy=(r.height-visibleH)/2;
 const px=(e.clientX-r.left-sx)/scale,py=(e.clientY-r.top-sy)/scale;
 if(px<0||py<0||px>=video.videoWidth||py>=video.videoHeight)return toast("Innerhalb des Kamerabilds klicken.");
 selected.push([px,py]);
 if(selected.length<5){toast("Punkt "+(selected.length+1)+"/5: "+labels[selected.length]+" anklicken.");return}
 phase="idle";
 try{
 const pos=verifyRefs(),cal=buildCameraCalibration(selected.slice(0,4),pos.slice(0,4));
 const verification=verifyCalibration(cal,selected[4],pos[4],1);
 if(!verification.passed){calibration=null;toast("Kalibrierung ungenau: unabhängiger Prüffehler "+verification.errorMm.toFixed(2)+" mm. Erneut kalibrieren.");return}
 cal.validated=true;cal.width=videoW;cal.height=videoH;cal.verificationErrorMm=verification.errorMm;calibration=cal;
 toast("Kalibriert · Prüffehler "+verification.errorMm.toFixed(2)+" mm. Stationäre Kamera nicht bewegen.");
 try{localStorage.setItem("lumacut.camera.calibration",JSON.stringify(cal))}catch{}
 }catch(err){calibration=null;toast("Kalibrierfehler: "+err.message)}
});
$("resetFiducials").onclick=()=>{phase="idle";selected=[];calibration=null;localStorage.removeItem("lumacut.camera.calibration");toast("Kalibrierung gelöscht.")};
$("cameraCapture").onclick=()=>{
 const v=$("cameraView");if(!v.videoWidth)return toast("Zuerst Kamera einschalten.");
 if(!calibration?.validated||calibration.width!==v.videoWidth||calibration.height!==v.videoHeight)return toast("Zuerst 5 Punkte kalibrieren und Genauigkeit prüfen.");
 const roi={x:Number($("scanX").value),y:Number($("scanY").value),w:Number($("scanW").value),h:Number($("scanH").value)};
 try{
 const input=document.createElement("canvas");input.width=v.videoWidth;input.height=v.videoHeight;const ctx=input.getContext("2d",{willReadFrequently:true});ctx.drawImage(v,0,0);
 const rgba=ctx.getImageData(0,0,input.width,input.height).data;
 const width=Math.min(1600,Math.max(1,Math.round(roi.w*3))),height=Math.min(1600,Math.max(1,Math.round(roi.h*3)));
 const warped=rectifyArea(rgba,input.width,input.height,calibration.machineToImage,roi,width,height);
 const out=$("scanResult");out.width=width;out.height=height;out.getContext("2d").putImageData(new ImageData(warped,width,height),0,0);
 toast("Maßstabsbezogener Bereich "+roi.w+" × "+roi.h+" mm aufgenommen. Genauigkeit: Prüffehler "+calibration.verificationErrorMm.toFixed(2)+" mm.");
 }catch(err){toast("Scan fehlgeschlagen: "+err.message)}
};
try{const saved=JSON.parse(localStorage.getItem("lumacut.camera.calibration")||"null");if(saved?.verified||saved?.validated)toast("Alte Kamera-Kalibrierung vorhanden. Nach Neustart oder Kamerabewegung neu kalibrieren.")}catch{}
