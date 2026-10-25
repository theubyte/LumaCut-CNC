import test from "node:test";import assert from "node:assert/strict";import {createUnifiedPlan,unifiedSummary} from "./unified-job.mjs";
const doc={layers:[{id:"engr",mode:"engrave",speed:1200,power:25,passes:1},{id:"cut",mode:"cut",speed:400,power:80,passes:2}],items:[{id:"c",kind:"rect",layer:"cut",x:40,y:50,w:20,h:10},{id:"a",kind:"image",layer:"engr",x:60,y:70,w:10,h:10}]};
const raster=new Map([["a",{width:2,height:2,rgba:new Uint8Array([0,0,0,255,255,255,255,255,0,0,0,255,255,255,255,255])}]]);
test("engraving precedes cut by layer order",()=>{const p=createUnifiedPlan(doc,raster);assert.deepEqual(p.operations.map(o=>o.type),["raster","vector"]);assert.equal(unifiedSummary(p).operations,2)});
test("missing image data fails closed",()=>assert.throws(()=>createUnifiedPlan(doc),/Missing image pixel data/));
test("orphaned layer fails closed",()=>assert.throws(()=>createUnifiedPlan({...doc,items:[{...doc.items[0],layer:"missing"}]},raster),/Orphaned/));
test("image on cutting layer blocked",()=>assert.throws(()=>createUnifiedPlan({...doc,items:[{...doc.items[1],layer:"cut"}]},raster),/engraving layer/));
