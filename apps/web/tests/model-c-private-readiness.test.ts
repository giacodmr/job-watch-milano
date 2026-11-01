import {execFileSync} from 'node:child_process';
import {describe,it,expect} from 'vitest';
import {resolve} from 'node:path';

describe('Milestone #44 no-credentials repository activation preflight',()=>{
  it('validates isolated configs and migration digests without claiming a Cloudflare account or deploy',()=>{
    const output=execFileSync(process.execPath,['tools/private-gate-preflight.mjs'],{
      cwd:resolve(import.meta.dirname,'..'),encoding:'utf8',timeout:15000,
      env:{...process.env,WRANGLER_SEND_METRICS:'false'},
    });
    const result=JSON.parse(output) as {
      gate:string;repositoryPreflight:string;activation:string;
      privateReadPath:string;privateWritePath:string;privateCommandActivation:string;
      serviceIngestion:string;remoteD1Bindings:string;
      cloudAccountVerified:boolean;cloudMutationsAuthorized:boolean;remoteImporterAuthorized:boolean;
      expectedSchemaVersions:{catalog:number;personal:number};
      migrations:Array<{scope:string;name:string;sha256:string}>;
      externalBlockers:string[];errors:string[];
    };
    expect(result.gate).toBe('A');
    expect(result.repositoryPreflight).toBe('PASSED');
    expect(result.errors).toEqual([]);
    expect(result.activation).toBe('BLOCKED_FOR_ACTIVATION');
    expect(result.privateReadPath).toBe('ACCESS_PROTECTED_LOCAL_TESTED');
    expect(result.privateWritePath).toBe('TWO_FLAG_GATE_B_REQUIRED');
    expect(result.privateCommandActivation).toBe('DISABLED_IN_COMMITTED_TEMPLATE');
    expect(result.serviceIngestion).toBe('DEPLOYABLE_DEFAULT_DENIED');
    expect(result.remoteD1Bindings).toBe('GATE_B_REQUIRED');
    expect(result.cloudAccountVerified).toBe(false);
    expect(result.cloudMutationsAuthorized).toBe(false);
    expect(result.remoteImporterAuthorized).toBe(false);
    expect(result.expectedSchemaVersions).toEqual({catalog:7,personal:3});
    expect(result.migrations.filter(m=>m.scope==='catalog')).toHaveLength(7);
    expect(result.migrations.filter(m=>m.scope==='personal')).toHaveLength(3);
    expect(result.migrations.every(m=>/^[a-f0-9]{64}$/.test(m.sha256))).toBe(true);
    expect(result.externalBlockers).toContain('GATE_B_APPROVAL_NOT_GRANTED');
    expect(result.externalBlockers).toContain('WRITE_GATE_AND_REMOTE_QUOTA_ATTESTATION_REQUIRED');
    expect(output).not.toMatch(/Cf-Access-Jwt-Assertion|Authorization: Bearer|PRIVATE_OWNER_ID=/);
  });
});
