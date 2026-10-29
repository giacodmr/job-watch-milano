import { z } from 'zod';
export class ApiError extends Error {
  constructor(public readonly code: string) {
    super(code);
  }
}
export async function readApi<T>(
  path: string,
  schema: z.ZodType<T>,
  signal: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    cache: 'no-store',
    signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]),
  });
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = z.object({ error: z.string() }).safeParse(body);
    throw new ApiError(error.success ? error.data.error : 'REQUEST_FAILED');
  }
  return schema.parse(body);
}
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.code === 'SNAPSHOT_CHANGED')
    return 'Lo snapshot è cambiato. Aggiorna l’inventario per consultare la nuova versione.';
  if (
    error instanceof ApiError &&
    ['invalid_query', 'INVALID_CURSOR', 'CURSOR_FILTER_MISMATCH'].includes(
      error.code,
    )
  )
    return 'I filtri o la pagina richiesta non sono validi. Reimposta i filtri e riprova.';
  return 'Impossibile leggere il database locale. Controlla che l’API sia avviata e le migrazioni siano applicate, poi riprova.';
}
export function dateLabel(value: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return 'Non disponibile';
  return new Intl.DateTimeFormat('it-IT', {
    dateStyle: 'short',
    timeStyle: 'short',
    timeZone: 'Europe/Rome',
  }).format(new Date(value));
}
export const labels: Record<string, string> = {
  NEW: 'Nuova',
  STILL_OPEN: 'Aperta',
  UPDATED: 'Aggiornata',
  CLOSED: 'Chiusa',
  UNKNOWN: 'Non verificata',
  INTERESTED: 'Interessato',
  TO_REVIEW: 'Da valutare',
  APPLIED: 'Candidatura inviata',
  NOT_INTERESTED: 'Non interessato',
  VERIFIED: 'Verificata',
  PARTIAL: 'Parziale',
  FAILED: 'Errore fonte',
  NOT_CHECKED: 'Non controllata',
  RETRY_PENDING: 'Recupero JD differito',
  JD_UNAVAILABLE: 'JD non disponibile',
  TOO_SENIOR: 'Esperienza richiesta',
  SALARY_TOO_LOW: 'Retribuzione',
  WRONG_FUNCTION: 'Funzione',
  WRONG_LOCATION: 'Sede',
  FIXED_TERM: 'Contratto a termine',
  PURE_SALES: 'Vendita pura',
  TOO_TECHNICAL: 'Contenuto tecnico',
  DOMAIN_GAP: 'Settore',
  OTHER: 'Altro',
};
export function githubSource(commit: string, path: string): string {
  return `https://github.com/giacodmr/job-watch-milano/blob/${encodeURIComponent(commit)}/${path.split('/').map(encodeURIComponent).join('/')}`;
}
