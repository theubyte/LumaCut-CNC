import test from "node:test";import assert from "node:assert/strict";import {validateProject} from "./project-validator.mjs";
const valid={schema:2,layers:[{id:"a",name:"Schneiden",mode:"cut",power:60,speed:700,passes:2}],items:[{id:"1",kind:"rect",layer:"a",x:30,y:40,w:100,h:40}],active:"a"};
test("valid editable project passes",()=>assert.equal(validateProject(valid),valid));
test("rejects layer orphan",()=>assert.throws(()=>validateProject({...valid,items:[{...valid.items[0],layer:"b"}]})));
test("rejects hostile bitmap URL in saved project",()=>assert.throws(()=>validateProject({...valid,items:[{...valid.items[0],kind:"image",data:"https://example.com/tracker.png"}]})));
test("rejects nonfinite points",()=>assert.throws(()=>validateProject({...valid,items:[{id:"1",kind:"free",layer:"a",x:30,y:40,points:[[30,40],[NaN,80]]}]})));
