import {createHmac,randomBytes} from 'node:crypto';
import {mkdirSync,writeFileSync,realpathSync} from 'node:fs';
import {dirname,isAbsolute,relative,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

// Offline only. No credential output, network access, overwrite or CI use.
const target=process.argv[2];
const repo=realpathSync(resolve(dirname(fileURLToPath(import.meta.url)),'../../..'));
if(process.env.CI||process.argv.length!==3||!target||!isAbsolute(target)){
  process.stderr.write('Use an absolute NEW private directory outside Git, in a trusted local terminal.\n');
  process.exit(1);
}
try{
  const destination=resolve(realpathSync(dirname(target)),target.split('/').at(-1));
  const rel=relative(repo,destination);
  if(!rel||(!rel.startsWith('../')&&!isAbsolute(rel)))throw Error('inside_repository');
  mkdirSync(destination,{mode:0o700}); // Exclusive: an existing directory fails.
  const credential='jw1_'+randomBytes(32).toString('base64url');
  const hmacKey=randomBytes(32);
  const secrets={PASSWORD_HMAC_KEY:hmacKey.toString('base64url'),
    PASSWORD_HMAC_VERIFIER:createHmac('sha256',hmacKey)
      .update('job-watch-login:v1\0'+credential).digest('base64url'),
    PASSWORD_SESSION_KEY:randomBytes(32).toString('base64url')};
  writeFileSync(resolve(destination,'worker-secrets.json'),JSON.stringify(secrets)+'\n',{mode:0o600,flag:'wx'});
  writeFileSync(resolve(destination,'login-password.txt'),credential+'\n',{mode:0o600,flag:'wx'});
  process.stdout.write('Private credential files created. No credential values displayed.\n');
}catch{
  // Never include input paths, payloads or exception detail in logs.
  process.stderr.write('Private generation failed; inspect the destination locally before retrying.\n');
  process.exit(1);
}
