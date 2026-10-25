import test from "node:test";import assert from "node:assert/strict";import fs from "node:fs";import path from "node:path";
const here=process.cwd(),html=fs.readFileSync(path.join(here,"index.html"),"utf8"),config=JSON.parse(fs.readFileSync(path.join(here,"src-tauri/tauri.conf.json"),"utf8")),pkg=JSON.parse(fs.readFileSync(path.join(here,"package.json"),"utf8"));
test("Windows app version synchronized",()=>assert.equal(config.version,pkg.version));
test("Tauri frontend directory is isolated",()=>assert.equal(config.build.frontendDist,"../dist"));
test("every local module and stylesheet exists",()=>{for(const match of html.matchAll(/(?:src|href)="\.\/([^"]+)"/g)){assert.ok(fs.existsSync(path.join(here,match[1])),match[1])}});
test("all local imports in advanced editor are shipped",()=>{const script=fs.readFileSync(path.join(here,"advanced.js"),"utf8");for(const m of script.matchAll(/from "\.\/([^"]+)"/g))assert.ok(fs.existsSync(path.join(here,m[1])),m[1])});
test("NSIS target selected",()=>assert.ok(config.bundle.targets.includes("nsis")));
