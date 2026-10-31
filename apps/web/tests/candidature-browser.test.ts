// Headless visual contract: actual React bundle -> local HTTP -> real Worker -> ephemeral D1.
// Synthetic fixtures only. Never deploys or accesses persistent databases.
import {beforeAll,afterAll,describe,it,expect} from 'vitest';
import {build} from 'esbuild';
import {Miniflare,convertV4MiniflareOptions} from 'miniflare';
import {applySchema} from '../tools/model-c-schema';
import {stageCatalog,publicationFixture,seedPersonal,owner} from './helpers/model-c-fixtures';
import {createServer} from 'node:http';
import type {Server} from 'node:http';
import {spawn} from 'node:child_process';
import type {ChildProcess} from 'node:child_process';
import {mkdtemp,readFile,rm,access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const delay=(ms:number)=>new Promise(resolve=>setTimeout(resolve,ms));
async function chromeBinary():Promise<string|null>{
  for(const path of ['/usr/bin/google-chrome','/usr/bin/google-chrome-stable','/usr/bin/chromium','/usr/bin/chromium-browser']){
    try {await access(path);return path;}catch{ /* try another installed browser */ }
  }
  return null;
}
type Session={send:(method:string,params?:Record<string,unknown>,sessionId?:string)=>Promise<any>;close:()=>void};
async function connectCDP(port:number,path:string):Promise<Session>{
  const ws=new WebSocket('ws://127.0.0.1:'+port+path);
  await new Promise<void>((resolve,reject)=>{
    ws.addEventListener('open',()=>resolve(),{once:true});
    ws.addEventListener('error',()=>reject(Error('CDP_CONNECT_FAILED')),{once:true});
  });
  let next=0;
  const pending=new Map<number,{resolve:(x:any)=>void;reject:(e:Error)=>void}>();
  ws.addEventListener('message',event=>{
    const msg=JSON.parse(String(event.data)) as {id?:number;result?:unknown;error?:{message:string}};
    if(msg.id===undefined)return;
    const item=pending.get(msg.id);if(!item)return;pending.delete(msg.id);
    if(msg.error)item.reject(Error(msg.error.message));else item.resolve(msg.result);
  });
  return {
    send(method,params={},sessionId){
      return new Promise((resolve,reject)=>{
        const id=++next;pending.set(id,{resolve,reject});
        ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
      });
    },
    close(){ws.close();for(const item of pending.values())item.reject(Error('CDP_CLOSED'));pending.clear();}
  };
}
async function capture(session:Session,tab:string,url:string,width:number,height:number,mobile:boolean){
  await session.send('Emulation.setDeviceMetricsOverride',
    {width,height,deviceScaleFactor:1,mobile},tab);
  await session.send('Page.navigate',{url},tab);
  let loaded=false;
  for(let attempt=0;attempt<100;attempt++){
    const result=await session.send('Runtime.evaluate',{
      expression:"Boolean(document.querySelector('.c-position strong')?.textContent?.includes('Synthetic Analyst'))",
      returnByValue:true,
    },tab);
    if(result?.result?.value===true){loaded=true;break;}
    await delay(100);
  }
  expect(loaded).toBe(true);
  const layout=await session.send('Runtime.evaluate',{
    expression:"({bodyWidth:document.body.scrollWidth,viewport:window.innerWidth,rows:document.querySelectorAll('.c-listing tbody tr').length,heading:document.querySelector('.c-heading h1')?.innerText})",
    returnByValue:true,
  },tab);
  expect(layout?.result?.value).toMatchObject({rows:1,heading:url.includes('/opportunita')?'Opportunità':'Candidature'});
  expect(layout?.result?.value?.bodyWidth).toBeLessThanOrEqual(width);
  const image=await session.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},tab);
  return image?.data as string;
}
let runtime:Miniflare,server:Server|null=null,chrome:ChildProcess|null=null,tempDir:string|null=null;
let url='';
beforeAll(async()=>{
  const [browser,workerBundle]=await Promise.all([
    build({entryPoints:['src/main.tsx'],bundle:true,write:false,format:'iife',platform:'browser',
      target:'es2022',jsx:'automatic',outdir:'/tmp/jw39-visual',loader:{'.css':'css'}}),
    build({entryPoints:['worker/index.ts'],bundle:true,write:false,format:'esm',platform:'browser',target:'es2023'}),
  ]);
  const js=browser.outputFiles.find(f=>f.path.endsWith('.js'))?.text;
  const css=browser.outputFiles.find(f=>f.path.endsWith('.css'))?.text;
  const workerJs=workerBundle.outputFiles.at(0)?.text;
  if(!js||!css||!workerJs)throw Error('VISUAL_BUNDLE_MISSING');
  runtime=new Miniflare(convertV4MiniflareOptions({modules:true,script:workerJs,
    compatibilityDate:'2026-10-29',cf:false,
    bindings:{APP_ENV:'local',MODEL_C_LOCAL_API:'synthetic-only',MODEL_C_TEST_OWNER:owner},
    d1Databases:{CATALOG:'visual-catalog',PERSONAL:'visual-personal'},
  }));
  const catalog=await runtime.getD1Database('CATALOG');
  const personal=await runtime.getD1Database('PERSONAL');
  await applySchema(catalog,'catalog');await applySchema(personal,'personal');
  await stageCatalog(catalog);await catalog.batch(publicationFixture(catalog,'run-one'));
  await seedPersonal(personal);
  server=createServer(async(request,response)=>{
    try{
      const path=request.url??'/';
      if(path==='/app.js'){response.setHeader('Content-Type','text/javascript');response.end(js);return;}
      if(path==='/app.css'){response.setHeader('Content-Type','text/css');response.end(css);return;}
      if(path.startsWith('/api/')){
        const result=await runtime.dispatchFetch('http://localhost'+path);
        response.statusCode=result.status;
        response.setHeader('Content-Type','application/json');
        response.end(await result.text());
        return;
      }
      response.setHeader('Content-Type','text/html; charset=utf-8');
      response.end('<!doctype html><html lang="it"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>');
    }catch{
      response.statusCode=503;response.end('Synthetic visual laboratory error');
    }
  });
  await new Promise<void>(resolve=>server?.listen(0,'127.0.0.1',resolve));
  const address=server.address();
  if(!address||typeof address==='string')throw Error('SERVER_ADDRESS_UNAVAILABLE');
  url='http://127.0.0.1:'+address.port+'/candidature';
  tempDir=await mkdtemp(join(tmpdir(),'jw39-chrome-'));
});
afterAll(async()=>{
  if(chrome && chrome.exitCode===null && chrome.signalCode===null) {
    await new Promise<void>(resolve=>{
      const safety=setTimeout(resolve,5000);
      chrome?.once('exit',()=>{clearTimeout(safety);resolve();});
      chrome?.kill('SIGKILL');
    });
  }
  if(server)await new Promise<void>(resolve=>server?.close(()=>resolve()));
  await runtime?.dispose();
  if(tempDir)await rm(tempDir,{recursive:true,force:true,maxRetries:12,retryDelay:200});
});
describe('Candidature actual browser layout and drawer against synthetic Model C HTTP',()=>{
  it('renders desktop/mobile responsive layout and interactive modal without horizontal overflow',async()=>{
    const bin=await chromeBinary();
    if(!bin)throw Error('CHROME_NOT_INSTALLED_VISUAL_QA_BLOCKED');
    if(!tempDir)throw Error('CHROME_TEMP_MISSING');
    chrome=spawn(bin,['--headless=new','--no-sandbox','--disable-gpu',
      '--disable-dev-shm-usage','--no-first-run','--no-default-browser-check',
      '--remote-allow-origins=*','--remote-debugging-port=0','--user-data-dir='+tempDir,
      'about:blank'],{stdio:'ignore'});
    const activeFile=join(tempDir,'DevToolsActivePort');
    let contents='';
    for(let i=0;i<100;i++){
      try {contents=await readFile(activeFile,'utf8');if(contents.trim())break;}catch{}
      await delay(100);
    }
    if(!contents)throw Error('CHROME_DEBUGGING_UNAVAILABLE');
    const [portString,endpoint]=contents.trim().split('\n');
    const port=Number(portString);
    if(!port||!endpoint)throw Error('CHROME_DEBUGGING_INVALID');
    const session=await connectCDP(port,endpoint);
    try{
      const target=await session.send('Target.createTarget',{url:'about:blank'});
      const attached=await session.send('Target.attachToTarget',{targetId:target.targetId,flatten:true});
      const tab=attached.sessionId as string;
      await session.send('Page.enable',{},tab);
      await session.send('Runtime.enable',{},tab);
      const desktop=await capture(session,tab,url,1440,900,false);
      expect(desktop?.length).toBeGreaterThan(1000);
      console.log('JW39_DESKTOP_PNG_BASE64='+desktop);
      const mobile=await capture(session,tab,url,390,844,true);
      expect(mobile?.length).toBeGreaterThan(1000);
      console.log('JW39_MOBILE_PNG_BASE64='+mobile);
      for(const [width,height,mobileMode] of [[1280,900,false],[768,1024,false],[320,720,true]] as const){
        const preview=await capture(session,tab,url,width,height,mobileMode);
        expect(preview?.length).toBeGreaterThan(1000);
        if(width===320)console.log('JW39_NARROW_PNG_BASE64='+preview);
      }
      await session.send('Runtime.evaluate',{
        expression:"document.querySelector('button.c-row-open')?.click()",
        returnByValue:true,
      },tab);
      let opened=false;
      for(let i=0;i<50;i++){
        const state=await session.send('Runtime.evaluate',{
          expression:"Boolean(document.querySelector('dialog.c-drawer[open]'))",
          returnByValue:true,
        },tab);
        if(state?.result?.value){opened=true;break;}
        await delay(100);
      }
      expect(opened).toBe(true);
      let detailLoaded=false;
      for(let i=0;i<60;i++){
        const state=await session.send('Runtime.evaluate',{
          expression:"Boolean(document.querySelector('.c-drawer-body .c-panel-section') && document.querySelector('.c-drawer-body')?.textContent?.includes('Decisione'))",
          returnByValue:true,
        },tab);
        if(state?.result?.value){detailLoaded=true;break;}
        await delay(100);
      }
      expect(detailLoaded).toBe(true);
      const drawer=await session.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},tab);
      expect(drawer?.data?.length).toBeGreaterThan(1000);
      console.log('JW39_MOBILE_DRAWER_PNG_BASE64='+drawer.data);
      const esc=await session.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27},tab);
      expect(esc).toBeDefined();
      await delay(150);
      const state=await session.send('Runtime.evaluate',{
        expression:"document.querySelector('dialog.c-drawer[open]')===null",returnByValue:true,
      },tab);
      expect(state?.result?.value).toBe(true);
      // PR #40: reuse the same live React/Worker/D1 fixture to validate both pages.
      const opportunityUrl=url.replace('/candidature','/opportunita');
      for(const [width,height,mobileMode] of [
        [1440,900,false],[1280,900,false],[768,1024,false],[390,844,true],[320,720,true],
      ] as const){
        const screenshot=await capture(session,tab,opportunityUrl,width,height,mobileMode);
        expect(screenshot?.length).toBeGreaterThan(1000);
        if(width===1440)console.log('JW40_DESKTOP_PNG_BASE64='+screenshot);
        if(width===390)console.log('JW40_MOBILE_PNG_BASE64='+screenshot);
        if(width===320)console.log('JW40_NARROW_PNG_BASE64='+screenshot);
      }
      const navigation=await session.send('Runtime.evaluate',{
        expression:"({active:document.querySelector('.c-nav-active')?.textContent?.trim(),breadcrumb:document.querySelector('.c-breadcrumb b')?.textContent,personal:document.body.textContent?.includes('Non interessato')})",
        returnByValue:true,
      },tab);
      expect(navigation?.result?.value).toMatchObject({
        active:'Opportunità',breadcrumb:'Opportunità',personal:true,
      });
      await session.send('Runtime.evaluate',{
        expression:"document.querySelector('button.c-row-open')?.click()",
        returnByValue:true,
      },tab);
      let hasDetails=false;
      for(let i=0;i<80;i++){
        const r=await session.send('Runtime.evaluate',{
          expression:"Boolean(document.querySelector('dialog.c-drawer[open] .c-panel-section .c-facts') && document.querySelector('.c-drawer-body')?.textContent?.includes('Prima osservazione'))",
          returnByValue:true,
        },tab);
        if(r?.result?.value){hasDetails=true;break;}
        await delay(100);
      }
      expect(hasDetails).toBe(true);
      const opportunityDrawer=await session.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},tab);
      console.log('JW40_DRAWER_PNG_BASE64='+opportunityDrawer?.data);
      await session.send('Runtime.evaluate',{
        expression:"[...document.querySelectorAll('.c-drawer-tabs button')].find(el=>el.textContent==='Provenienza')?.click()",
        returnByValue:true,
      },tab);
      const sources=await session.send('Runtime.evaluate',{
        expression:"document.querySelector('.c-drawer-body')?.textContent?.includes('Synthetic Company::old')",
        returnByValue:true,
      },tab);
      expect(sources?.result?.value).toBe(true);
      await session.send('Input.dispatchKeyEvent',{
        type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27,
      },tab);
      await delay(150);
      const closed=await session.send('Runtime.evaluate',{
        expression:"document.querySelector('dialog.c-drawer[open]')===null",returnByValue:true,
      },tab);
      expect(closed?.result?.value).toBe(true);
    }finally{session.close();}
  },125000);
});
