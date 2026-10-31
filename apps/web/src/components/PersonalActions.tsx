import {useEffect,useRef,useState} from 'react';
import type {PersonalRow,Decision} from '../model-c-personal-client';
import {decisionLabel,readPersonalWriteCapabilities} from '../model-c-personal-client';
import {
  CommandFailure,commandMessage,forgetPending,newCommand,pendingFor,
  postPersonalCommand,rememberPending,
} from '../model-c-personal-commands';
import type {PersonalCommand} from '../model-c-personal-commands';

/** Shared by Candidature and Opportunità. Local synthetic write gate is server-owned. */
export function PersonalActions({
  row,jobId,catalogRevision,onReload,onConfirmed,
}:{
  row:PersonalRow|null;jobId:string;catalogRevision:number;
  onReload:()=>Promise<void>;onConfirmed:()=>void;
}){
  const [enabled,setEnabled]=useState(false);
  const [capabilityLoading,setCapabilityLoading]=useState(true);
  const [choice,setChoice]=useState<Decision|''>(row?.decision??'');
  const [reason,setReason]=useState('');
  const [busy,setBusy]=useState(false);
  const [pending,setPending]=useState<PersonalCommand|null>(()=>pendingFor(jobId));
  const [confirmApplied,setConfirmApplied]=useState(false);
  const [status,setStatus]=useState('');
  const [issue,setIssue]=useState('');
  const [locked,setLocked]=useState(false);
  const busyRef=useRef(false);
  const confirmationRef=useRef<HTMLButtonElement>(null);

  useEffect(()=>{
    const controller=new AbortController();
    setCapabilityLoading(true);setEnabled(false);
    readPersonalWriteCapabilities(controller.signal)
      .then(value=>{if(!controller.signal.aborted)setEnabled(value.writeEnabled);})
      .catch(()=>{if(!controller.signal.aborted)setEnabled(false);})
      .finally(()=>{if(!controller.signal.aborted)setCapabilityLoading(false);});
    return ()=>controller.abort();
  },[]);
  useEffect(()=>{
    setChoice(row?.decision??'');setReason('');setConfirmApplied(false);
  },[jobId,row?.jobRevision,row?.decision]);
  useEffect(()=>{
    setPending(pendingFor(jobId));setIssue('');setStatus('');setLocked(false);
  },[jobId]);
  useEffect(()=>{
    if(confirmApplied)confirmationRef.current?.focus();
  },[confirmApplied]);

  const saved=row?.activeReferences.includes('SAVED')??false;
  const revision=row?.jobRevision??0;
  const disabled=!enabled||busy||!!pending||locked;
  const decision=(choice||null) as Decision|null;
  const changed=decision!==(row?.decision??null);
  const feedback=issue||status;

  async function refreshAfterWrite(){
    try {
      await onReload();
      setLocked(false);
      return true;
    }catch{
      setLocked(true);
      setIssue('Modifica registrata, ma aggiornamento non riuscito. Ricarica il dettaglio prima di proseguire.');
      return false;
    }
  }
  async function execute(command:PersonalCommand){
    if(busyRef.current)return;
    busyRef.current=true;setBusy(true);setStatus('Registrazione in corso…');setIssue('');
    rememberPending(command);setPending(command);
    try{
      const receipt=await postPersonalCommand(command);
      forgetPending(jobId);setPending(null);
      setConfirmApplied(false);
      const synced=await refreshAfterWrite();
      onConfirmed();
      if(synced){setStatus(receipt.replayed?'Operazione verificata e registrata.':'Modifica salvata.');setIssue('');}
    }catch(error){
      if(error instanceof CommandFailure && error.uncertain){
        setPending(command);setIssue(commandMessage(error));setStatus('');
      }else{
        forgetPending(jobId);setPending(null);
        setIssue(commandMessage(error));setStatus('');
        if(error instanceof CommandFailure && ['REVISION_CONFLICT','CATALOG_CHANGED','JOB_NOT_CURRENT'].includes(error.code)){
          setLocked(true);
          try{await onReload();setLocked(false);}
          catch{setIssue('La posizione è cambiata, ma non è possibile aggiornarla. Riprova la lettura.');}
        }
      }
    }finally{busyRef.current=false;setBusy(false);}
  }
  function setDecision(){
    if(disabled||!changed)return;
    if(decision==='APPLIED'){setConfirmApplied(true);return;}
    void execute(newCommand({kind:'DECISION',jobId,catalogRevision,
      expectedRevision:revision,decision,reasonSummary:decision==='NOT_INTERESTED'?reason.trim()||null:null}));
  }
  function setSaved(){
    if(disabled)return;
    void execute(newCommand({kind:'SAVED',jobId,catalogRevision,expectedRevision:revision,active:!saved}));
  }
  async function reload(){
    if(busyRef.current)return;
    setLocked(true);setIssue('');
    try{await onReload();setLocked(false);setStatus('Stato aggiornato.');}
    catch{setIssue('Impossibile leggere lo stato attuale. Riprova.');}
  }

  return <section className="c-personal-actions" aria-label="Azioni personali">
    <h3>Le tue azioni</h3>
    {capabilityLoading&&<p className="c-action-note" role="status">Verifica disponibilità delle modifiche…</p>}
    {!capabilityLoading&&!enabled&&<p className="c-action-note">Modalità di sola lettura. Le modifiche non sono abilitate in questo ambiente.</p>}
    {enabled&&<>
      <div className="c-action-field">
        <label htmlFor={'decision-'+jobId}>Decisione personale</label>
        <div className="c-action-controls">
          <select id={'decision-'+jobId} value={choice} disabled={disabled}
            onChange={event=>{setChoice(event.target.value as Decision|'');setConfirmApplied(false);setIssue('');}}>
            <option value="">Nessuna decisione (revoca)</option>
            {Object.entries(decisionLabel).map(([value,label])=><option key={value} value={value}>{label}</option>)}
          </select>
          <button type="button" className="c-btn c-btn-dark" disabled={disabled||!changed} onClick={setDecision}>Conferma decisione</button>
        </div>
        {choice==='NOT_INTERESTED'&&<label className="c-action-reason">Motivo facoltativo
          <textarea maxLength={360} rows={2} value={reason} disabled={disabled}
            onChange={event=>setReason(event.target.value)} placeholder="Puoi aggiungere una breve nota"/>
        </label>}
      </div>
      {confirmApplied&&<div className="c-action-confirm" role="group" aria-label="Conferma candidatura inviata">
        <p>Hai già inviato la candidatura per questa posizione? Job Watch registra solo la tua dichiarazione, senza invii esterni.</p>
        <div className="c-action-buttons">
          <button ref={confirmationRef} type="button" className="c-btn c-btn-dark" disabled={disabled}
            onClick={()=>void execute(newCommand({kind:'DECISION',jobId,catalogRevision,
              expectedRevision:revision,decision:'APPLIED',reasonSummary:null}))}>Conferma candidatura inviata</button>
          <button type="button" className="c-btn" disabled={busy}
            onClick={()=>setConfirmApplied(false)}>Annulla</button>
        </div>
      </div>}
      <div className="c-action-saved">
        <div><strong>Salvata</strong><p>{saved?'Questa posizione è nei tuoi salvati.':'Aggiungi la posizione ai tuoi salvati.'}</p></div>
        <button type="button" className="c-btn" disabled={disabled} onClick={setSaved}>
          {saved?'Rimuovi dai salvati':'Salva posizione'}</button>
      </div>
      {pending&&!busy&&<div className="c-action-retry" role="group" aria-label="Operazione incerta">
        <p>È presente un'operazione il cui esito non è confermato. Verrà riutilizzata la stessa chiave di richiesta.</p>
        <button type="button" className="c-btn c-btn-dark" onClick={()=>void execute(pending)}>Verifica e riprova</button>
      </div>}
      {locked&&!pending&&!busy&&<button type="button" className="c-btn" onClick={()=>void reload()}>Ricarica stato</button>}
    </>}
    {!!feedback&&<p className={'c-action-feedback'+(issue?' c-error':'')} role={issue?'alert':'status'} aria-live="polite">{feedback}</p>}
  </section>;
}
