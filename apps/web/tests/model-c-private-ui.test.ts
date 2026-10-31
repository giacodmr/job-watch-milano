import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {describe,expect,it} from 'vitest';
import {OpportunityTable} from '../src/Opportunita';
import {resolveOpportunityPersonal} from '../src/model-c-opportunities-client';
import type {Opportunity,OpportunityDetail} from '../src/model-c-opportunities-client';

const recorded={decision:'APPLIED',activeReferences:['SAVED'],
  assessment:{fitScore:95,freshness:'CURRENT'}} as unknown as Opportunity['personal'];
const job={id:'job:'+'1'.repeat(64),title:'Analyst',company:'Test Company',
  location:null,lifecycle:'NEW',lastSeenAt:null,needsAnalysis:false,
  technicalStatus:null,workerEligible:null,personal:recorded} as Opportunity;

describe('Private UI — authoritative PERSONAL readiness',()=>{
  it('never displays previously cached personal decisions or FIT without a verified PERSONAL revision',()=>{
    const html=renderToStaticMarkup(createElement(OpportunityTable,{
      items:[job],personalAvailable:false,
    }));
    expect(html).toContain('Registro non disponibile');
    expect(html).not.toContain('Candidatura inviata');
    expect(html).not.toContain('FIT 95');
    expect(html).not.toContain('Nessuna decisione');
    expect(html).toContain('Analyst');
  });
  it('distinguishes genuinely empty verified PERSONAL from an unimported PERSONAL database',()=>{
    const clean={...job,personal:null};
    const verified=renderToStaticMarkup(createElement(OpportunityTable,{
      items:[clean],personalAvailable:true,
    }));
    expect(verified).toContain('Nessuna decisione');
    expect(verified).not.toContain('Registro non disponibile');
    const unavailable=renderToStaticMarkup(createElement(OpportunityTable,{
      items:[clean],personalAvailable:false,
    }));
    expect(unavailable).toContain('Registro non disponibile');
  });
  it('uses null in a fresh detail rather than falling back to a stale row overlay',()=>{
    const unavailable={personal:null} as OpportunityDetail;
    expect(resolveOpportunityPersonal(job,unavailable)).toBeNull();
    expect(resolveOpportunityPersonal(job,null)).toBe(recorded);
    expect(resolveOpportunityPersonal({personal:null},null)).toBeNull();
  });
});
