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
export function unifiedSummary(plan){let length=0,passes=0;for(const op of plan.operations){passes+=op.process.passes;if(op.type==="vector")for(const p of op.paths)for(let i=1;i<p.length;i++)length+=Math.hypot(p[i][0]-p[i-1][0],p[i][1]-p[i-1][1])*op.process.passes;else if(op.type==="raster")for(const line of op.lines)for(const s of line.segments)length+=Math.abs(s.x1-s.x0)*op.process.passes}return {operations:plan.operations.length,passes,pathMm:length}}
