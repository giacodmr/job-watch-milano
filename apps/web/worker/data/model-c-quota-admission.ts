// M49: conservative account-wide CATALOG quota reservation ledger.
// Ingestion, trusted importer, and private APP commands reserve against the
// same existing catalog_write_reservations SQL guard. This is NOT a remote
// Cloudflare account quota observation or a cross-D1 transaction.
export type QuotaAttestation = {
  PRIVATE_QUOTA_ATTESTED?:string;
  PRIVATE_INGESTION_QUOTA_REMAINING?:string;
  PRIVATE_INGESTION_QUOTA_VALID_UNTIL?:string;
};
export type WriteBudget={operatorVerified:true;writeUnitsRemaining:number;day:string};
export function verifiedWriteBudget(env:QuotaAttestation, now=Date.now()):WriteBudget|undefined{
  const raw=env.PRIVATE_INGESTION_QUOTA_REMAINING;
  const expiry=env.PRIVATE_INGESTION_QUOTA_VALID_UNTIL;
  if(env.PRIVATE_QUOTA_ATTESTED!=='verified-under-budget'||!raw||!expiry||
    !/^(?:0|[1-9][0-9]{0,4})$/.test(raw)||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(expiry))
    return undefined;
  const remaining=Number(raw),deadline=Date.parse(expiry);
  if(!Number.isSafeInteger(remaining)||remaining<100||remaining>30000||
     !Number.isFinite(deadline)||deadline<=now||deadline>now+300000)
    return undefined;
  return {operatorVerified:true,writeUnitsRemaining:remaining,
    day:new Date(now).toISOString().slice(0,10)};
}
export function reservationStatements(db:D1Database,budget:WriteBudget,units:number){
 if(!Number.isSafeInteger(units)||units<1||units>1000)
   throw Error('M49_RESERVATION_INVALID');
 return [
  db.prepare('INSERT INTO catalog_write_days VALUES (?,0) ON CONFLICT DO NOTHING')
    .bind(budget.day),
  db.prepare('INSERT INTO catalog_write_reservations VALUES (?,?,?,?)')
    .bind(crypto.randomUUID(),budget.day,units,budget.writeUnitsRemaining),
 ];
}
/** Reserve before a PERSONAL command. If a cross-D1 write later fails, leave
 * its conservative reservation charged rather than risk double spending.
 * The resulting accounting is an upper bound, not billed rows_written. */
export async function reservePersonalWriteBudget(db:D1Database,budget:WriteBudget,units=32){
 const results=await db.batch(reservationStatements(db,budget,units));
 // D1.batch() rejects on an SQL failure and rolls the batch back. The D1
 // result type exposes success as the literal true, so comparing it to false
 // is impossible (TS2367). A missing receipt is not an accepted reservation.
 if(results.length!==2)
   throw Error('M49_QUOTA_RESERVATION_FAILED');
 return {reservedUnits:units,chargedByAccountLedger:true as const};
}
