import test from "node:test";import assert from "node:assert/strict";import {createUnifiedPlan,exportUnifiedDraft} from "./unified-job.mjs";
const layers=[{id:"e",mode:"engrave",speed:1300,power:20,passes:1},{id:"c",mode:"cut",speed:400,power:70,passes:2}];
const items=[{id:"img",layer:"e",kind:"image",x:40,y:60,w:10,h:10},{id:"rect",layer:"c",kind:"rect",x:80,y:90,w:10,h:10}];
const raster=new Map([["img",{width:1,height:1,rgba:new Uint8Array([0,0,0,255])}]]);
test("combined export contains both operations in layer order",()=>{const code=exportUnifiedDraft(createUnifiedPlan({layers,items},raster));assert.ok(code.indexOf("; Layer e")<code.indexOf("; Layer c"));assert.match(code,/M4 S200/);assert.match(code,/M4 S700/);assert.ok(code.trim().endsWith("M2"));});
test("invalid preview coordinate cannot be emitted",()=>{const p=createUnifiedPlan({layers,items},raster);p.operations[0].lines[0].segments[0].x0=-5;assert.throws(()=>exportUnifiedDraft(p),/Unsafe/)});
test("every laser-on preceded by a travel-off",()=>{const code=exportUnifiedDraft(createUnifiedPlan({layers,items},raster)).split("\n");for(let i=0;i<code.length;i++)if(code[i].startsWith("M4 S"))assert.match(code[i-1],/^G0 X/);});
