// LumaCut Studio -> Pi 400 Marlin 2.1 offline postprocessor.
// This only generates a file for review. It NEVER starts machinery.
export const MARLIN_PROFILE = Object.freeze({
  id:"lumacut-pi400-marlin",name:"LumaCut Pi 400 · Marlin",
  travelX:390,travelY:370,homingReserve:30,pwmMax:255,laserMode:"M3 I",
});
const valid=n=>typeof n==="number"&&Number.isFinite(n);
function xy(x,y){if(!valid(x)||!valid(y)||x<MARLIN_PROFILE.homingReserve||y<MARLIN_PROFILE.homingReserve||x>MARLIN_PROFILE.travelX||y>MARLIN_PROFILE.travelY)throw Error("Coordinate outside configured Marlin work zone");return `X${x.toFixed(3)} Y${y.toFixed(3)}`;}
function check(line){if(!line||line.length>96||!(/^[\x20-\x7E]*$/.test(line)))throw Error("Invalid or non-ASCII Marlin command");}
export function postprocessMarlinOffline(plan){
 if(plan?.kind!=="LumaCutOfflinePlan"||plan.version!==1||!Array.isArray(plan.operations)||!plan.operations.length)throw Error("Invalid plan");
 const out=["; LUMACUT MARLIN OFFLINE DRAFT - NOT VALIDATED FOR REAL MACHINE","; REQUIRES HOMING, FOCUS, INTERLOCK AND MACHINE GEOMETRY VERIFICATION","G21","G90","M5 I"];
 for(const op of plan.operations){
  const p=op.process;if(!valid(p.feed)||p.feed<=0||p.feed>6000||!valid(p.power)||p.power<0||p.power>100||!Number.isInteger(p.passes)||p.passes<1||p.passes>30)throw Error("Invalid layer settings");
  const power=Math.round(p.power/100*MARLIN_PROFILE.pwmMax);
  out.push("; LAYER "+String(op.layer).replace(/[^\x20-\x7E]/g,"?").slice(0,72));
  for(let pass=0;pass<p.passes;pass++){
   out.push(`; PASS ${pass+1} OF ${p.passes}`);
   if(op.type==="vector"){
    for(const path of op.paths){
     if(!Array.isArray(path)||path.length<2)throw Error("Invalid vector");
     const coords=path.map(point=>xy(point[0],point[1]));
     out.push("M5 I",`G0 ${coords[0]}`,"M3 I");
     for(const coord of coords.slice(1))out.push(`G1 ${coord} F${p.feed} S${power}`);
     out.push("M5 I");
    }
   }else if(op.type==="raster"){
    for(const row of op.lines){
     const segs=row.reverse?[...row.segments].reverse():row.segments;
     for(const segment of segs){
      const a=row.reverse?segment.x1:segment.x0,b=row.reverse?segment.x0:segment.x1;
      out.push("M5 I",`G0 ${xy(a,row.y)}`,"M3 I",`G1 ${xy(b,row.y)} F${p.feed} S${power}`,"M5 I");
     }
    }
   }else throw Error("Unsupported operation");
  }
 }
 out.push("M5 I","M400");
 out.filter(line=>!line.startsWith(";")).forEach(check);
 return out.join("\n")+"\n";
}
