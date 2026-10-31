// Browser-only Model C command contract. Never import a Worker module into React.
import {z} from 'zod';

const jobId=z.string().regex(/^job:[a-f0-9]{64}$/);
const base={
  jobId,operationId:z.string().uuid(),
  expectedRevision:z.number().int().min(0).max(2147483646),
  catalogRevision:z.number().int().positive().max(2147483646),
};
export const decisionCommandSchema=z.strictObject({
  ...base,kind:z.literal('DECISION'),
  decision:z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']).nullable(),
  reasonSummary:z.string().trim().max(360).nullable().default(null),
});
export const savedCommandSchema=z.strictObject({
  ...base,kind:z.literal('SAVED'),active:z.boolean(),
});
export const commandSchema=z.discriminatedUnion('kind',[decisionCommandSchema,savedCommandSchema]);
export type PersonalCommand=z.infer<typeof commandSchema>;
export const commandResultSchema=z.object({
  status:z.literal('saved'),replayed:z.boolean(),productionAccess:z.literal(false),
  eventId:z.string(),operationId:z.string().uuid(),jobId,
  jobRevision:z.number().int().positive(),
  decision:z.enum(['TO_REVIEW','INTERESTED','APPLIED','NOT_INTERESTED']).nullable(),
  saved:z.boolean(),
});
export type CommandResult=z.infer<typeof commandResultSchema>;

const route=(kind:PersonalCommand['kind'])=>
  '/api/model-c/personal/commands/'+(kind==='DECISION'?'decision':'saved');
export class CommandFailure extends Error {
  constructor(readonly code:string,readonly status:number,readonly uncertain:boolean){
    super(code);
  }
}
export function newCommand(
  input:{jobId:string;catalogRevision:number;expectedRevision:number} &
    ({kind:'DECISION';decision:PersonalCommand['decision'];reasonSummary?:string|null}|
     {kind:'SAVED';active:boolean}),
):PersonalCommand{
  return commandSchema.parse({...input,operationId:crypto.randomUUID()});
}
/** Timeout/transport failure after POST is NOT proof of rollback. */
export async function postPersonalCommand(input:PersonalCommand):Promise<CommandResult>{
  const command=commandSchema.parse(input);
  let response:Response;
  try {
    response=await fetch(route(command.kind),{
      method:'POST',cache:'no-store',credentials:'same-origin',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(command),
      signal:AbortSignal.timeout(15000),
    });
  }catch{
    throw new CommandFailure('OUTCOME_UNCERTAIN',0,true);
  }
  let body:unknown;
  try{body=await response.json();}
  catch{throw new CommandFailure('OUTCOME_UNCERTAIN',response.status,true);}
  if(!response.ok){
    const error=z.object({error:z.string()}).safeParse(body);
    const code=error.success?error.data.error:'REQUEST_FAILED';
    // A server failure after a possibly committed request is not a known rollback.
    throw new CommandFailure(code,response.status,response.status>=500);
  }
  const parsed=commandResultSchema.safeParse(body);
  if(!parsed.success || parsed.data.operationId!==command.operationId||
    parsed.data.jobId!==command.jobId){
    throw new CommandFailure('OUTCOME_UNCERTAIN',response.status,true);
  }
  return parsed.data;
}

const prefix='job-watch:synthetic:pending:';
function storage():Storage|null{
  try{return typeof sessionStorage==='undefined'?null:sessionStorage;}catch{return null;}
}
/** The tab-scoped record preserves retry identity, not application state. */
export function pendingFor(job:string):PersonalCommand|null{
  const store=storage();if(!store)return null;
  try{
    const raw=store.getItem(prefix+job);
    if(!raw)return null;
    const parsed=commandSchema.safeParse(JSON.parse(raw));
    return parsed.success&&parsed.data.jobId===job?parsed.data:null;
  }catch{return null;}
}
export function rememberPending(command:PersonalCommand){
  try{storage()?.setItem(prefix+command.jobId,JSON.stringify(command));}catch{
    // In-memory hook state still keeps the uncertain command until unmount.
  }
}
export function forgetPending(job:string){
  try{storage()?.removeItem(prefix+job);}catch{/* Storage disabled. */}
}
export function commandMessage(error:unknown):string {
  if(!(error instanceof CommandFailure))return 'Non è possibile verificare il salvataggio.';
  if(error.uncertain)return 'Esito non confermato. Verifica o riprova la stessa operazione, senza crearne un’altra.';
  switch(error.code){
    case 'REVISION_CONFLICT':return 'Questa posizione è cambiata. Controlla lo stato aggiornato e conferma nuovamente.';
    case 'CATALOG_CHANGED':return 'Il catalogo è stato aggiornato. Verifica la posizione prima di confermare.';
    case 'IDEMPOTENCY_KEY_REUSED':return 'Operazione non valida: la chiave è già stata utilizzata per un’altra modifica.';
    case 'JOB_NOT_CURRENT':return 'La posizione non è più disponibile per questa modifica.';
    case 'not_found':return 'La scrittura non è abilitata in questo ambiente.';
    default:return 'La modifica non è stata registrata. Verifica i dati e riprova.';
  }
}
