import { healthSchema, schemaVersion } from '../shared/contracts';
import { z } from 'zod';
import { jobsQuerySchema } from '../shared/queries';
import { getSnapshot, listJobs, getJob, getDashboard, QueryError } from './data/queries';

export interface Env {
  APP_ENV?: string;
  DB?: D1Database;
  ASSETS?: Fetcher;
}

function json(
  body: unknown,
  status = 200,
  extraHeaders?: HeadersInit,
): Response {
  const headers = new Headers(extraHeaders);
  headers.set('Content-Type', 'application/json; charset=utf-8');
  headers.set('Cache-Control', 'no-store');
  headers.set('X-Content-Type-Options', 'nosniff');
  return new Response(JSON.stringify(body), { status, headers });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    // Local development boundary, not an authentication mechanism. No remote
    // runtime is enabled until verified Access JWT authentication is implemented.
    if (
      env.APP_ENV !== 'local' ||
      !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    ) {
      return json({ error: 'remote_runtime_disabled' }, 403);
    }
    if (url.pathname === '/api/health') {
      if (request.method !== 'GET')
        return json({ error: 'method_not_allowed' }, 405, { Allow: 'GET' });
      if (url.search)
        return json({ error: 'unexpected_query_parameters' }, 400);
      let database: 'ready' | 'unavailable' | 'migration_required' =
        'unavailable';
      let actualVersion: number | null = null;
      try {
        const row = await env.DB?.prepare(
          'SELECT version FROM schema_metadata WHERE id = 1',
        ).first<{ version: number }>();
        actualVersion = row?.version ?? null;
        database = !env.DB
          ? 'unavailable'
          : actualVersion === schemaVersion
            ? 'ready'
            : 'migration_required';
      } catch {
        // Never log SQL errors, request bodies, credentials or operational data.
        database = 'unavailable';
      }
      const body = healthSchema.parse({
        service: 'job-watch-web',
        environment: 'local',
        status: database === 'ready' ? 'ok' : 'degraded',
        database,
        schemaVersion: actualVersion,
        expectedSchemaVersion: schemaVersion,
        productionAccess: false,
        synchronization: 'local-read-only',
        checkedAt: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
      });
      return json(body, database === 'ready' ? 200 : 503);
    }
    if (url.pathname === '/api/commands') {
      if (request.method !== 'POST')
        return json({ error: 'method_not_allowed' }, 405, { Allow: 'POST' });
      return json({ error: 'commands_disabled', phase: 1 }, 501);
    }
    if (
      url.pathname === '/api/snapshot' ||
      url.pathname === '/api/dashboard' ||
      url.pathname === '/api/jobs' ||
      url.pathname.startsWith('/api/jobs/')
    ) {
      if (request.method !== 'GET')
        return json({ error: 'method_not_allowed' }, 405, { Allow: 'GET' });
      if (!env.DB) return json({ error: 'database_unavailable' }, 503);
      try {
        const entries = Array.from(url.searchParams.entries());
        if (new Set(entries.map(([key]) => key)).size !== entries.length)
          return json({ error: 'duplicate_query_parameter' }, 400);
        const input = Object.fromEntries(entries);
        if (url.pathname === '/api/snapshot') {
          z.strictObject({}).parse(input);
          return json(await getSnapshot(env.DB));
        }
        if (url.pathname === '/api/dashboard') {
          z.strictObject({}).parse(input);
          return json(await getDashboard(env.DB));
        }
        if (url.pathname === '/api/jobs')
          return json(await listJobs(env.DB, jobsQuerySchema.parse(input)));
        const params = z
          .strictObject({
            snapshot: z.string().regex(/^snapshot:[a-f0-9]{64}$/),
          })
          .parse(input);
        const id = z
          .string()
          .regex(/^job:[a-f0-9]{64}$/)
          .parse(url.pathname.slice('/api/jobs/'.length));
        return json(await getJob(env.DB, id, params.snapshot));
      } catch (error) {
        if (error instanceof z.ZodError)
          return json({ error: 'invalid_query' }, 400);
        if (error instanceof QueryError)
          return json({ error: error.code }, error.status);
        return json({ error: 'database_unavailable' }, 503);
      }
    }
    if (url.pathname === '/api' || url.pathname.startsWith('/api/'))
      return json({ error: 'not_found' }, 404);
    if (!['GET', 'HEAD'].includes(request.method))
      return json({ error: 'method_not_allowed' }, 405, { Allow: 'GET, HEAD' });
    if (!env.ASSETS) return json({ error: 'assets_unavailable' }, 503);
    const response = await env.ASSETS.fetch(request);
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', 'no-store');
    headers.set('X-Content-Type-Options', 'nosniff');
    headers.set('Referrer-Policy', 'no-referrer');
    headers.set(
      'Content-Security-Policy',
      "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
    );
    return new Response(response.body, { status: response.status, headers });
  },
};
