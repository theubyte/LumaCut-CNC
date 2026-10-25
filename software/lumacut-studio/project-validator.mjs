// Document integrity checks used by load, autosave and the offline planner.
const finite=v=>typeof v==="number"&&Number.isFinite(v);
export function validateProject(data){
 if(!data||data.schema!==2||!Array.isArray(data.layers)||!Array.isArray(data.items))throw Error("Ungültiges LumaCut-Projektformat");
 if(data.layers.length<1||data.layers.length>100||data.items.length>3000)throw Error("Projekt überschreitet Objekt- oder Ebenenlimits");
 const ids=new Set();
 for(const l of data.layers){
  if(typeof l.id!=="string"||l.id.length>80||ids.has(l.id))throw Error("Ungültige oder doppelte Ebenenkennung");
  ids.add(l.id);
  if(!["cut","engrave"].includes(l.mode)||!finite(l.power)||l.power<0||l.power>100||!finite(l.speed)||l.speed<=0||l.speed>6000||!Number.isInteger(l.passes)||l.passes<1||l.passes>30)throw Error("Ungültige Ebenenparameter");
  if(typeof l.name!=="string"||l.name.length>80)throw Error("Ungültiger Ebenenname");
 }
 let vertices=0;
 for(const o of data.items){
  if(typeof o.id!=="string"||!ids.has(o.layer)||!["rect","ellipse","line","free","text","image"].includes(o.kind))throw Error("Ungültiges Projektobjekt");
  if(!finite(o.x)||!finite(o.y)||o.x<0||o.y<0||o.x>390||o.y>370)throw Error("Ungültige Objektposition");
  if(o.kind==="free"){
   if(!Array.isArray(o.points)||o.points.length<2||o.points.length>25000)throw Error("Ungültiger Freihandpfad");
   vertices+=o.points.length;
   if(o.points.some(p=>!Array.isArray(p)||p.length!==2||!p.every(finite)))throw Error("Ungültiger Freihandpunkt");
  }else if(o.kind==="text"){
   if(typeof o.text!=="string"||o.text.length>2000)throw Error("Ungültiger Text");
  }else{
   if(!finite(o.w)||!finite(o.h)||(o.kind!=="line"&&(o.w<0||o.h<0)))throw Error("Ungültige Objektgröße");
  }
  if(o.kind==="image"&&(!/^data:image\/(png|jpeg|webp);base64,/.test(o.data)||o.data.length>6000000))throw Error("Ungültiges Bildformat oder Dateigröße");
 }
 if(vertices>100000)throw Error("Zu viele Vektorpunkte");
 if(!ids.has(data.active))throw Error("Aktive Ebene nicht vorhanden");
 return data;
}
