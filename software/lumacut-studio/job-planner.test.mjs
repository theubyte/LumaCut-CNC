import test from "node:test";import assert from "node:assert/strict";import {planVectorJob,planStatistics} from "./job-planner.mjs";
const project={layers:[{id:"cut",name:"Schneiden",mode:"cut",power:65,speed:750,passes:2}],items:[{id:"r",layer:"cut",kind:"rect",x:35,y:40,w:10,h:20}]};
test("rectangle creates closed bounded path and two passes",()=>{const p=planVectorJob(project);assert.equal(p[0].paths[0].length,5);assert.equal(planStatistics(p).lengthMm,120)});
test("safe zone is forbidden",()=>assert.throws(()=>planVectorJob({...project,items:[{...project.items[0],y:29}]}),/usable area/));
test("raster cannot be silently exported",()=>assert.throws(()=>planVectorJob({...project,items:[{id:"i",layer:"cut",kind:"image",x:35,y:40,w:10,h:20}]}),/separate validated planner/));
test("bad power blocked",()=>assert.throws(()=>planVectorJob({...project,layers:[{...project.layers[0],power:110}]}),/Invalid layer/));
