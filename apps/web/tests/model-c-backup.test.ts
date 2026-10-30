import {execFileSync} from 'node:child_process';
import {it,expect} from 'vitest';
it('writes private synthetic backup files and restores all three scopes without persistent inputs',()=>{
  const result=JSON.parse(execFileSync('node',['tools/model-c-lab.mjs'],{encoding:'utf8',stdio:['ignore','pipe','pipe']}));
  expect(result).toMatchObject({status:'SYNTHETIC_SCHEMA_RESTORE_VERIFIED',ephemeralOnly:true,persistentDatabaseTouched:false,backupsRemoved:true});
  expect(result.scopes).toHaveLength(3);
  for(const scope of result.scopes){expect(scope.replay).toMatchObject({applied:0,rowsWritten:0});expect(scope.restored.verified).toBe(true);expect(scope.fileMode).toBe('0600');}
},60_000);
