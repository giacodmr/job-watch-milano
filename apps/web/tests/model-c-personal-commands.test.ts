import {afterEach,describe,it,expect,vi} from 'vitest';
import {
  commandSchema,forgetPending,newCommand,pendingFor,
  postPersonalCommand,rememberPending,
} from '../src/model-c-personal-commands';

const id='job:'+'1'.repeat(64);
const command=()=>newCommand({
  kind:'DECISION',jobId:id,catalogRevision:1,expectedRevision:0,
  decision:'INTERESTED',reasonSummary:null,
});
const ok=(cmd:ReturnType<typeof command>,replayed=false)=>new Response(JSON.stringify({
  status:'saved',productionAccess:false,operationId:cmd.operationId,
  jobId:cmd.jobId,replayed,eventId:'app:'+cmd.operationId,
  jobRevision:1,decision:'INTERESTED',saved:false,
}),{status:200,headers:{'Content-Type':'application/json'}});
afterEach(()=>vi.unstubAllGlobals());

describe('PR #42 browser command contract',()=>{
  it('uses the exact PR41 payload, route, UUID and same-origin JSON POST',async()=>{
    const cmd=command();
    expect(cmd.operationId).toMatch(/^[0-9a-f]{8}-/);
    const fetch=vi.fn(async()=>ok(cmd));vi.stubGlobal('fetch',fetch);
    expect(await postPersonalCommand(cmd)).toMatchObject({status:'saved',replayed:false,jobRevision:1});
    const [url,options]=fetch.mock.calls[0] as unknown as [string,RequestInit];
    expect(url).toBe('/api/model-c/personal/commands/decision');
    expect(options.method).toBe('POST');
    expect(options.credentials).toBe('same-origin');
    expect(options.cache).toBe('no-store');
    expect(new Headers(options.headers).get('content-type')).toBe('application/json');
    expect(JSON.parse(String(options.body))).toEqual(cmd);
  });
  it('keeps SAVED independent and never accepts an invented status, key or field',async()=>{
    const saved=newCommand({kind:'SAVED',jobId:id,catalogRevision:1,expectedRevision:0,active:true});
    const fetch=vi.fn(async()=>new Response(JSON.stringify({
      ...JSON.parse(await ok(command()).text()),operationId:saved.operationId,
      eventId:'app:'+saved.operationId,saved:true,decision:null,
    }),{status:200}));vi.stubGlobal('fetch',fetch);
    expect(await postPersonalCommand(saved)).toMatchObject({saved:true,decision:null});
    expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe('/api/model-c/personal/commands/saved');
    expect(commandSchema.safeParse({...saved,decision:'APPLIED'}).success).toBe(false);
    expect(commandSchema.safeParse({...command(),decision:'CUSTOM'}).success).toBe(false);
    expect(commandSchema.safeParse({...command(),expectedRevision:-1}).success).toBe(false);
  });
  it('classifies timeout, network and malformed success as uncertain, not failure',async()=>{
    const cmd=command();
    for(const outcome of [async()=>Promise.reject(new TypeError('offline')),
      async()=>new Response('not JSON',{status:200})]){
      vi.stubGlobal('fetch',vi.fn(outcome));
      await expect(postPersonalCommand(cmd)).rejects.toMatchObject({
        code:'OUTCOME_UNCERTAIN',uncertain:true,
      });
    }
  });
  it('returns exact 409 codes while marking 503 as uncertain',async()=>{
    const cmd=command();
    vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({error:'REVISION_CONFLICT'}),{status:409})));
    await expect(postPersonalCommand(cmd)).rejects.toMatchObject({
      code:'REVISION_CONFLICT',status:409,uncertain:false,
    });
    vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({error:'WRITE_TRANSACTION_FAILED'}),{status:503})));
    await expect(postPersonalCommand(cmd)).rejects.toMatchObject({
      status:503,uncertain:true,
    });
  });
  it('preserves identical retry payload in tab-scoped storage and clears only upon definitive resolution',()=>{
    const values=new Map<string,string>();
    vi.stubGlobal('sessionStorage',{
      getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>values.set(k,v),
      removeItem:(k:string)=>values.delete(k),
    });
    const cmd=command();
    rememberPending(cmd);
    expect(pendingFor(id)).toEqual(cmd);
    expect(pendingFor('job:'+'2'.repeat(64))).toBeNull();
    forgetPending(id);expect(pendingFor(id)).toBeNull();
  });
});
