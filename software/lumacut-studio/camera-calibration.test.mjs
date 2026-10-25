import test from "node:test";import assert from "node:assert/strict";import {buildCameraCalibration,verifyCalibration,rectifyArea} from "./camera-calibration-core.mjs";
const m=[[30,30],[330,30],[330,330],[30,330]],p=[[100,90],[700,90],[700,690],[100,690]];
test("manual camera calibration maps image and machine coordinates",()=>{const c=buildCameraCalibration(p,m);const v=verifyCalibration(c,[400,390],[180,180]);assert.ok(v.passed);assert.ok(v.errorMm<1e-6)});
test("independent fifth point fails accuracy check",()=>{const c=buildCameraCalibration(p,m);assert.equal(verifyCalibration(c,[450,390],[180,180]).passed,false)});
test("degenerate fiducials rejected",()=>assert.throws(()=>buildCameraCalibration([[1,1],[2,2],[3,3],[4,4]],m)));
test("rectification rejects reserved area",()=>{const c=buildCameraCalibration(p,m);assert.throws(()=>rectifyArea(new Uint8Array(16),2,2,c.machineToImage,{x:20,y:29,w:10,h:10},2,2),/Invalid rectification/)});
test("rectification output has RGBA shape",()=>{const c=buildCameraCalibration([[0,0],[3,0],[3,3],[0,3]],[[30,30],[33,30],[33,33],[30,33]]);const pixels=new Uint8ClampedArray(4*4*4).fill(128);const out=rectifyArea(pixels,4,4,c.machineToImage,{x:30.5,y:30.5,w:2,h:2},2,2);assert.equal(out.length,16);assert.ok(out[0]>0)});
