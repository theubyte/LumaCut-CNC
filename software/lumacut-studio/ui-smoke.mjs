import {chromium} from "playwright";
import {createServer} from "node:http";
import {readFile,mkdir} from "node:fs/promises";
import path from "node:path";
const cwd=process.cwd();
const mime={".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".mjs":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".svg":"image/svg+xml"};
const server=createServer(async(req,res)=>{
 try{
  const target=path.resolve(cwd,"."+decodeURIComponent(new URL(req.url,"http://localhost").pathname));
  if(!target.startsWith(cwd+path.sep))throw Error("outside root");
  const body=await readFile(target);
  res.setHeader("Content-Type",mime[path.extname(target)]||"application/octet-stream");
  res.end(body);
 }catch{res.statusCode=404;res.end("Not found")}
});
await new Promise(resolve=>server.listen(0,"127.0.0.1",resolve));
let browser,page;
try{
 for(const channel of ["chrome","msedge"]){
  try{browser=await chromium.launch({channel,headless:true,args:["--disable-gpu"]});break}catch(err){console.warn(channel+" unavailable: "+err.message.slice(0,180))}
 }
 if(!browser)throw Error("No installed Chrome/Edge browser found for UI acceptance tests");
 const context=await browser.newContext({acceptDownloads:true,viewport:{width:1600,height:950}});
 page=await context.newPage();
 const errors=[];
 page.on("pageerror",error=>errors.push(error.message));
 await page.goto("http://127.0.0.1:"+server.address().port+"/index.html");
 await page.waitForSelector("#layerList .layer");
 if(await page.locator("#layerList .layer").count()!==2)throw Error("Default layers failed to initialize");
 await page.locator('[data-tool="rect"]').click();
 const box=await page.locator("#editorOverlay").boundingBox();
 if(!box)throw Error("Editor overlay missing");
 const x=box.x+box.width*.30,y=box.y+box.height*.35;
 await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+box.width*.20,y+box.height*.10,{steps:8});await page.mouse.up();
 await page.waitForSelector("#objectList button");
 if(await page.locator("#objectList button").count()!==1)throw Error("Rectangle not saved in editor");
 await page.locator("#objectList button").first().click();
 await page.locator("#shapeX").fill("75");
 await page.locator("#applyGeometry").click();
 const actual=await page.locator("#drawings rect").first().getAttribute("x");
 if(Math.abs(Number(actual)-75)>.001)throw Error("Numeric geometry inspector did not update shape position: "+actual);
 await page.locator('[data-tab="process"]').click();
 await page.locator("#planUnified").click();
 await page.waitForFunction(()=>document.querySelector("#unifiedInfo")?.textContent.includes("Vorgänge"));
 const marlin=page.locator("#exportMarlinDraft");
 if(!await marlin.isVisible())throw Error("Pi400 Marlin export control missing");
 const downloadPromise=page.waitForEvent("download");
 await marlin.click();
 const download=await downloadPromise;
 if(!download.suggestedFilename().endsWith(".gcode"))throw Error("Marlin export filename invalid");
 const message=await page.locator("#toast").textContent();
 if(!message.includes("Marlin"))throw Error("Marlin export status missing");
 await page.locator('[data-tab="camera"]').click();
 if(!await page.locator("#startFiducials").isVisible())throw Error("Camera calibration controls unavailable");
 if(errors.length)throw Error("Browser JavaScript exception(s): "+errors.join(" ; "));
 console.log("LumaCut UI SMOKE SUCCESS: layers, rectangle, numeric editing, unified plan, Marlin download, camera controls.");
}finally{
 if(page){await mkdir(path.join(cwd,"test-artifacts"),{recursive:true});await page.screenshot({path:path.join(cwd,"test-artifacts","windows-ui.png"),fullPage:true}).catch(()=>{});}
 await browser?.close();await new Promise(resolve=>server.close(resolve));
}
