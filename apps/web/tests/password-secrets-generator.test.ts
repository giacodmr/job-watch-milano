import {it,expect} from 'vitest';
import {execFileSync,spawnSync} from 'node:child_process';
import {mkdtempSync,readFileSync,statSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHmac} from 'node:crypto';
it('generates private, independent CSPRNG credentials without output, overwrite or CI use',()=>{
 const parent=mkdtempSync(join(tmpdir(),'jw-secret-test-'));
 const destination=join(parent,'private');
 const env={...process.env,CI:''};
 try{
  const out=execFileSync(process.execPath,['tools/generate-password-secrets.mjs',destination],{encoding:'utf8',env});
  const credential=readFileSync(join(destination,'login-password.txt'),'utf8').trim();
  const secrets=JSON.parse(readFileSync(join(destination,'worker-secrets.json'),'utf8'));
  expect(/^jw1_[A-Za-z0-9_-]{43}$/.test(credential)).toBe(true);
  expect(Buffer.from(credential.slice(4),'base64url').length).toBe(32);
  expect(createHmac('sha256',Buffer.from(secrets.PASSWORD_HMAC_KEY,'base64url'))
   .update('job-watch-login:v1\0'+credential).digest('base64url')===secrets.PASSWORD_HMAC_VERIFIER).toBe(true);
  expect(secrets.PASSWORD_HMAC_KEY===secrets.PASSWORD_SESSION_KEY).toBe(false);
  for(const value of [credential,...Object.values(secrets) as string[]])expect(out.includes(value)).toBe(false);
  expect(statSync(destination).mode&0o777).toBe(0o700);
  for(const file of ['login-password.txt','worker-secrets.json'])expect(statSync(join(destination,file)).mode&0o777).toBe(0o600);
  for(const [target,childEnv] of [[destination,env],[join(parent,'ci'),{...env,CI:'true'}],[join(process.cwd(),'forbidden-secret-dir'),env]]){
   expect(spawnSync(process.execPath,['tools/generate-password-secrets.mjs',target as string],{env:childEnv as NodeJS.ProcessEnv}).status).not.toBe(0);
  }
  expect(readFileSync(join(destination,'login-password.txt'),'utf8').trim()===credential).toBe(true);
 }finally{rmSync(parent,{recursive:true,force:true});}
});
