import {planVectorJob} from "./job-planner.mjs";
import {rasterLines,ditherGray} from "./raster-planner.mjs";
// Offline-only unified planner. rasterData is a Map from image object ID to {rgba,width,height}.
export function createUnifiedPlan(project,rasterData=new Map(),options={lineSpacing:0.15,dither:"threshold"}){
 if(!project||!Array.isArray(project.layers)||!Array.isArray(project.items))throw Error("Invalid document");
 const idSet=new Set();for(const layer of project.layers){if(idSet.has(layer.id))throw Error("Duplicate layer ID");idSet.add(layer.id)}
 for(const item of project.items)if(!idSet.has(item.layer))throw Error("Orphaned object: "+item.id);
 const operations=[];
 for(const layer of project.layers){
  const objects=project.items.filter(o=>o.layer===layer.id);
  if(!objects.length)continue;
  const process={mode:layer.mode,feed:layer.speed,power:layer.power,passes:layer.passes};
  if(!["cut","engrave"].includes(process.mode)||!Number.isFinite(process.feed)||process.feed<=0||process.feed>6000||!Number.isFinite(process.power)||process.power<0||process.power>100||!Number.isInteger(process.passes)||process.passes<1||process.passes>30)throw Error("Invalid layer process settings");
  for(const obj of objects){
   if(obj.kind==="text")throw Error("Text must be converted to outlines before planning");
   if(obj.kind==="image"){
    if(process.mode!=="engrave")throw Error("Image must be on engraving layer");
    const data=rasterData.get(obj.id);if(!data)throw Error("Missing image pixel data: "+obj.id);
    const pixels=ditherGray(data.rgba,data.width,data.height,options.dither);
    const lines=rasterLines(pixels,data.width,data.height,obj,options.lineSpacing);
    operations.push({layer:layer.id,object:obj.id,type:"raster",process,lines});
   }else{
    const planned=planVectorJob({layers:[layer],items:[obj]});
    operations.push({layer:layer.id,object:obj.id,type:"vector",process,paths:planned[0].paths});
   }
  }
 }
 if(!operations.length)throw Error("No executable operations");
 return {kind:"LumaCutOfflinePlan",version:1,operations};
}
export function unifiedSummary(plan){
 let length=0,passes=0;
 for(const op of plan.operations){
  passes+=op.process.passes;
  if(op.type==="vector"){
   for(const p of op.paths)for(let i=1;i<p.length;i++)length+=Math.hypot(p[i][0]-p[i-1][0],p[i][1]-p[i-1][1])*op.process.passes;
  }else if(op.type==="raster"){
   for(const line of op.lines)for(const seg of line.segments)length+=Math.abs(seg.x1-seg.x0)*op.process.passes;
  }
 }
 return {operations:plan.operations.length,passes,pathMm:length};
}

function validatePoint(x,y){if(!Number.isFinite(x)||!Number.isFinite(y)||x<0||x>390||y<30||y>370)throw Error("Unsafe or invalid machine-preview coordinate")}
export function exportUnifiedDraft(plan){
 if(plan?.kind!=="LumaCutOfflinePlan"||plan.version!==1||!Array.isArray(plan.operations)||!plan.operations.length)throw Error("Invalid offline job plan");
 const out=["; LUMACUT UNIFIED OFFLINE DRAFT","; UNSAFE FOR LIVE MACHINE: UNVALIDATED COORDINATE SYSTEM, Z, HOMING AND INTERLOCKS","G21","G90","M5"];
 for(const op of plan.operations){
  const p=op.process;
  if(!Number.isFinite(p.feed)||p.feed<=0||p.feed>6000||!Number.isFinite(p.power)||p.power<0||p.power>100||!Number.isInteger(p.passes)||p.passes<1||p.passes>30)throw Error("Invalid process");
  const laser=Math.round(p.power*10);
  out.push("; Layer "+String(op.layer).replace(/[\r\n]/g," "),"; Object "+String(op.object).replace(/[\r\n]/g," "));
  for(let pass=0;pass<p.passes;pass++){
   out.push("; Pass "+(pass+1));
   if(op.type==="vector"){
    for(const path of op.paths){
     if(path.length<2)throw Error("Invalid path");
     for(const [x,y] of path)validatePoint(x,y);
     out.push("M5",`G0 X${path[0][0].toFixed(3)} Y${path[0][1].toFixed(3)}`,`M4 S${laser}`);
     for(const [x,y] of path.slice(1))out.push(`G1 X${x.toFixed(3)} Y${y.toFixed(3)} F${p.feed}`);
     out.push("M5");
    }
   }else if(op.type==="raster"){
    for(const line of op.lines){
     const segments=line.reverse?[...line.segments].reverse():line.segments;
     for(const segment of segments){
      const ax=line.reverse?segment.x1:segment.x0,bx=line.reverse?segment.x0:segment.x1;
      validatePoint(ax,line.y);validatePoint(bx,line.y);
      out.push("M5",`G0 X${ax.toFixed(3)} Y${line.y.toFixed(3)}`,`M4 S${laser}`,`G1 X${bx.toFixed(3)} Y${line.y.toFixed(3)} F${p.feed}`,"M5");
     }
    }
   }else throw Error("Unsupported operation");
  }
 }
 out.push("M5","M2");return out.join("\n")+"\n";
}
