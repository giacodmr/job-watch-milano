import {pbkdf2Sync,randomBytes} from 'node:crypto';

// Offline helper. Run in your own trusted terminal, NOT in a Codex transcript.
// NEVER commit, screenshot, paste into chat or log these one-time secrets.
const password=randomBytes(32).toString('base64url');
const salt=randomBytes(16);
const verifier=pbkdf2Sync(password,salt,100_000,32,'sha256');
const key=randomBytes(32);
process.stdout.write([
  'COPY TO A PRIVATE PASSWORD MANAGER AND CLOUDFLARE SECRETS ONLY.',
  'DO NOT RUN IN LOGGED CI OR AN AGENT TRANSCRIPT.',
  '',
  'LOGIN_PASSWORD='+password,
  'PASSWORD_PBKDF2_SALT='+salt.toString('base64url'),
  'PASSWORD_PBKDF2_VERIFIER='+verifier.toString('base64url'),
  'PASSWORD_SESSION_KEY='+key.toString('base64url'),
  '',
  'No credentials were written to disk. These values are lost when the terminal closes.',
].join('\n')+'\n');
