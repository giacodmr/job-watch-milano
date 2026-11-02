// Local-only synthetic workerd measurements. No credentials, remote bindings or deployment.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createHmac,pbkdf2Sync} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {cpus,platform,arch} from 'node:os';
import {performance} from 'node:perf_hooks';
import {dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {Miniflare,convertV4MiniflareOptions,Request} from 'miniflare';

const baseline=process.argv.length===3&&process.argv[2]==='--baseline';
assert(process.argv.length===2||baseline,'LOCAL_SYNTHETIC_BENCHMARK_INVALID_ARGUMENT');
const baselineSource=()=>execFileSync('git',['show','c579a255c3fe90e684d7e6260f0ee8c686c3638e:apps/web/worker/password-auth.ts'],{encoding:'utf8'});
const app=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const host='password-benchmark.example.test',origin='https://'+host;
// Public, intentionally unusable synthetic fixture. Never run the real secret generator here.
const password='jw1_'+Buffer.alloc(32,11).toString('base64url'),salt=Buffer.alloc(32,7);
const bundle=await build({entryPoints:[resolve(app,'worker/index.ts')],bundle:true,
  plugins:baseline?[{name:'baseline-auth',setup(b){b.onLoad({filter:/password-auth\.ts$/},()=>({contents:baselineSource(),loader:'ts'}));}}]:[],write:false,format:'esm',platform:'browser',target:'es2023'});
const fixture={APP_ENV:'password',PASSWORD_HOSTNAME:host,PRIVATE_OWNER_ID:'benchmark-owner',
  PASSWORD_HMAC_KEY:salt.toString('base64url'),
  PASSWORD_HMAC_VERIFIER:createHmac('sha256',salt).update('job-watch-login:v1\0'+password).digest('base64url'),
  PASSWORD_SESSION_KEY:Buffer.alloc(32,9).toString('base64url')};
if(baseline){
  fixture.PASSWORD_PBKDF2_SALT=Buffer.alloc(16,7).toString('base64url');
  fixture.PASSWORD_PBKDF2_VERIFIER=pbkdf2Sync(password,Buffer.alloc(16,7),100000,32,'sha256').toString('base64url');
}
function runtime(limit){
  return new Miniflare(convertV4MiniflareOptions({modules:true,script:bundle.outputFiles[0].text,
    compatibilityDate:'2026-10-29',cf:false,bindings:fixture,
    d1Databases:{CATALOG:'benchmark-catalog',PERSONAL:'benchmark-personal'},
    ratelimits:{PASSWORD_RATE_LIMITER:{namespace_id:'1001',simple:{limit,period:60}}}}));
}
function cpuMilliseconds(){
  // Descendants of this harness only; excludes other tests/Workers and Node-side fixture setup.
  const rows=execFileSync('ps',['-ax','-o','pid=,ppid=,comm='],{encoding:'utf8'}).trim().split('\n')
    .map(line=>/^\s*(\d+)\s+(\d+)\s+(.+)$/.exec(line)).filter(Boolean);
  const descendants=new Set([process.pid]);
  for(let size=-1;size!==descendants.size;){
    size=descendants.size;
    for(const row of rows)if(descendants.has(Number(row[2])))descendants.add(Number(row[1]));
  }
  const workers=rows.filter(row=>descendants.has(Number(row[1]))&&/workerd$/.test(row[3]));
  assert(workers.length>0,'LOCAL_WORKERD_PROCESS_NOT_FOUND');
  return workers.reduce((sum,row)=>{
    const time=execFileSync('ps',['-p',row[1],'-o','time='],{encoding:'utf8'}).trim();
    const parts=time.split(':').map(Number);
    return sum+parts.reduce((seconds,part)=>seconds*60+part,0)*1000;
  },0);
}
const login=(value)=>new Request(origin+'/login',{method:'POST',redirect:'manual',
  headers:{Origin:origin,'Content-Type':'application/x-www-form-urlencoded'},
  body:new URLSearchParams({password:value}).toString()});
let mf,limited;
try{
  mf=runtime(1000);
  for(let i=0;i<5;i++)await (await mf.dispatchFetch(login(password))).arrayBuffer();
  const scenarios=[];
  async function measure(name,count,makeRequest,expected){
    const samples=[],before=cpuMilliseconds();
    for(let i=0;i<count;i++){
      const start=performance.now(),response=await mf.dispatchFetch(makeRequest());
      assert.equal(response.status,expected);await response.arrayBuffer();
      samples.push(performance.now()-start);
    }
    const cpu=cpuMilliseconds()-before;
    samples.sort((a,b)=>a-b);
    scenarios.push({name,requests:count,wall_ms_p50:samples[Math.floor(count/2)],
      wall_ms_p95:samples[Math.ceil(count*.95)-1],wall_ms_max:samples[count-1],
      workerd_process_cpu_ms_total:cpu,workerd_process_cpu_ms_per_request:cpu/count});
  }
  await measure('login_page_no_kdf',30,()=>new Request(origin+'/login'),200);
  await measure('invalid_credential_verification',30,()=>login('jw1_'+Buffer.alloc(32,12).toString('base64url')),303);
  await measure('valid_credential_verification_and_sign',30,()=>login(password),303);
  const signed=await mf.dispatchFetch(login(password));
  const cookie=signed.headers.get('set-cookie').split(';')[0];await signed.arrayBuffer();
  await measure('authenticated_session_no_d1',60,()=>new Request(origin+'/api/model-c/private/status',{
    headers:{Cookie:cookie}}),200);
  await mf.dispose();mf=undefined;
  limited=runtime(5);
  const statuses=[];
  for(let i=0;i<12;i++){
    const response=await limited.dispatchFetch(login('jw1_'+Buffer.alloc(32,12).toString('base64url')));
    statuses.push(response.status);assert.equal(response.headers.get('set-cookie'),null);
    await response.arrayBuffer();
  }
  assert(statuses.includes(429),'LOCAL_RATE_LIMIT_NOT_OBSERVED');
  const workerd=JSON.parse(await readFile(resolve(app,'node_modules/workerd/package.json'),'utf8'));
  console.log(JSON.stringify({localOnly:true,syntheticOnly:true,remoteCalls:0,
    node:process.version,workerd:workerd.version,platform:platform(),arch:arch(),cpu:cpus()[0]?.model,
    baseline,algorithm:baseline?'PBKDF2-HMAC-SHA256-100000':'HMAC-SHA256-256bit-random-credential',scenarios,
    localRateLimit:{threshold:5,period_seconds:60,statuses},
    cloudFreeCpuCertified:false,
    limitation:'Host wall time and aggregate local workerd process CPU (ps, coarse resolution) are not per-invocation billed Cloudflare CPU. Remote CPU, distributed limiter overshoot and edge asset routing require separate Gate B.'},null,2));
}finally{await mf?.dispose();await limited?.dispose();}
