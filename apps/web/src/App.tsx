import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { jobsResponseSchema, snapshotResponseSchema } from "../shared/queries";
import type { JobView, JobsResponse, SnapshotView } from "../shared/queries";
import { ApiError, dateLabel, errorMessage, labels, readApi } from "./api";
import JobDetail from "./JobDetail";

function assessment(job: JobView) {
  if (job.decision === "APPLIED" || job.decision === "NOT_INTERESTED")
    return "Scelta utente persistente";
  if (job.hardExclusionReason) return "Esclusa da regola";
  if (job.needsAnalysis)
    return job.workerEligible ? "Da analizzare" : "Analisi in attesa tecnica";
  if (job.analysisMethod?.startsWith("chatgpt_semantic"))
    return job.reportable === null
      ? "Valutazione disponibile"
      : job.reportable
        ? "Segnalabile · ChatGPT"
        : "Non segnalabile · ChatGPT";
  return job.lifecycle === "CLOSED" ? "Identità storica" : "Non proiettata";
}

export default function App() {
  const [query, setQuery] = useState(
    () => window.location.search.slice(1) || "lifecycle=OPEN",
  );
  const [advancedOpen, setAdvancedOpen] = useState(() =>
    ["batch", "assessment", "decision"].some((key) =>
      new URLSearchParams(window.location.search).has(key),
    ),
  );
  const [refresh, setRefresh] = useState(0);
  const [snapshot, setSnapshot] = useState<SnapshotView | null>(null);
  const [page, setPage] = useState<JobsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingImports, setPendingImports] = useState(0);
  const [selected, setSelected] = useState<JobView | null>(null);
  const params = new URLSearchParams(query);
  const filterKey = Array.from(params)
    .filter(([key]) => key !== "cursor")
    .toString();
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setPage(null);
    setSelected(null);
    Promise.all([
      readApi("/api/snapshot", snapshotResponseSchema, controller.signal),
      readApi("/api/jobs?" + query, jobsResponseSchema, controller.signal),
    ])
      .then(([context, data]) => {
        if (controller.signal.aborted) return;
        if (data.snapshotId !== (context.snapshot?.id ?? null))
          throw new ApiError("SNAPSHOT_CHANGED");
        setSnapshot(context.snapshot);
        setPendingImports(context.pendingImports);
        setPage(data);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [query, refresh]);

  function navigate(next: URLSearchParams) {
    if (!next.has("lifecycle")) next.set("lifecycle", "ALL");
    const value = next.toString();
    window.history.replaceState(
      null,
      "",
      value ? "?" + value : window.location.pathname,
    );
    setQuery(value);
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = new URLSearchParams();
    for (const [key, value] of new FormData(event.currentTarget)) {
      if (typeof value === "string" && value.trim())
        next.set(key, value.trim());
    }
    if (next.toString() === query) setRefresh((value) => value + 1);
    else navigate(next);
  }
  function reload() {
    const next = new URLSearchParams(query);
    next.delete("cursor");
    navigate(next);
    setRefresh((value) => value + 1);
  }
  const select = (name: string, title: string, options: [string, string][]) => (
    <label>
      {title}
      <select name={name} defaultValue={params.get(name) || ""}>
        {options.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Vai all’inventario
      </a>
      <header className="app-header">
        <a href="/" className="brand" translate="no">
          <span className="brand-mark" aria-hidden="true">
            JW
          </span>
          Job Watch
        </a>
        <nav aria-label="Navigazione principale">
          <a href="#main" aria-current="page">
            Opportunità
          </a>
        </nav>
        <span className="mode-label">Locale · Sola lettura</span>
      </header>
      <main id="main">
        <div className="page-heading">
          <div>
            <h1>Opportunità</h1>
            <p className="secondary">
              Inventario e storico dalle fonti operative di Job Watch.
            </p>
          </div>
          <button type="button" onClick={reload} disabled={loading}>
            Aggiorna inventario
          </button>
        </div>
        {error && (
          <div role="alert" className="error-banner">
            <h2>Consultazione non disponibile</h2>
            <p>{error}</p>
            <button
              type="button"
              onClick={() => {
                navigate(new URLSearchParams("lifecycle=OPEN"));
                setRefresh((value) => value + 1);
              }}
            >
              Reimposta e riprova
            </button>
          </div>
        )}
        {!error && loading && !snapshot && (
          <p role="status" className="empty-state">
            Lettura del database locale…
          </p>
        )}
        {!error && !loading && !snapshot && (
          <section className="empty-state">
            <h2>Nessuno snapshot confermato</h2>
            <p>
              Il database non contiene ancora un inventario pubblicato per la
              consultazione.
            </p>
            <p className="secondary">
              Importa un commit Git verificato con il comando locale documentato
              nel progetto. Nessun job o KPI viene simulato.
            </p>
            {pendingImports > 0 && (
              <p>
                È presente un import incompleto. Riprendilo prima di consultare
                i dati.
              </p>
            )}
          </section>
        )}
        {!error && snapshot && (
          <>
            <div className="snapshot-line">
              <span>
                Import confermato{" "}
                <time dateTime={snapshot.confirmedAt}>
                  {dateLabel(snapshot.confirmedAt)}
                </time>
              </span>
              <span>
                Fonti dal {dateLabel(snapshot.oldestSourceAt)} al{" "}
                {dateLabel(snapshot.newestSourceAt)} · Europe/Rome
              </span>
            </div>
            {snapshot.pendingImports > 0 && (
              <p className="notice" role="status">
                Import incompleto in staging. Stai consultando l’ultimo snapshot
                confermato.
              </p>
            )}
            <details className="sync-details">
              <summary>Provenienza e stato della pipeline</summary>
              <dl className="facts">
                <div>
                  <dt>Commit sorgente</dt>
                  <dd>
                    <a
                      href={`https://github.com/giacodmr/job-watch-milano/commit/${snapshot.commitSha}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <code>{snapshot.commitSha.slice(0, 12)}</code>
                    </a>
                  </dd>
                </div>
                <div>
                  <dt>Revisione locale</dt>
                  <dd>{snapshot.revision}</dd>
                </div>
                <div>
                  <dt>Raccolta</dt>
                  <dd>{snapshot.collectionStatus || "Non disponibile"}</dd>
                </div>
                <div>
                  <dt>Certificazione</dt>
                  <dd>{snapshot.healthStatus || "Non disponibile"}</dd>
                </div>
                <div>
                  <dt>Daily completo</dt>
                  <dd>
                    {snapshot.dailyComplete === null
                      ? "Non disponibile"
                      : snapshot.dailyComplete
                        ? "Sì"
                        : "No"}
                  </dd>
                </div>
                <div>
                  <dt>Semantica completa</dt>
                  <dd>
                    {snapshot.fullSemanticComplete === null
                      ? "Non disponibile"
                      : snapshot.fullSemanticComplete
                        ? "Sì"
                        : "No"}
                  </dd>
                </div>
              </dl>
              <p className="secondary">
                Questi stati provengono dal Job Watch Python. L’esito
                dell’import locale non certifica il completamento della
                pipeline.
              </p>
            </details>
            <form
              onSubmit={submit}
              className="filters"
              key={filterKey}
              aria-label="Filtri opportunità"
            >
              <label className="search-field">
                Cerca opportunità
                <input
                  name="q"
                  type="search"
                  defaultValue={params.get("q") || ""}
                  placeholder="Es. Strategy Analyst…"
                  maxLength={120}
                  autoComplete="off"
                />
              </label>
              {select("company", "Azienda", [
                ["", "Tutte le aziende"],
                ...snapshot.companies.map(
                  (company) => [company.id, company.name] as [string, string],
                ),
              ])}
              {select("lifecycle", "Ciclo di vita", [
                ["ALL", "Tutti gli stati"],
                ["OPEN", "Aperte"],
                ...["NEW", "STILL_OPEN", "UPDATED", "CLOSED", "UNKNOWN"].map(
                  (value) =>
                    [value, labels[value] || value] as [string, string],
                ),
              ])}
              <button
                type="button"
                className="advanced-toggle quiet"
                aria-expanded={advancedOpen}
                aria-controls="advanced-filters"
                onClick={() => setAdvancedOpen((value) => !value)}
              >
                {advancedOpen ? "Nascondi filtri avanzati" : "Filtri avanzati"}
              </button>
              <div
                id="advanced-filters"
                className="advanced-filters"
                data-open={advancedOpen}
              >
                {select("batch", "Batch", [
                  ["", "Tutti i batch"],
                  ...["jw1", "jw2", "jw3", "jw4"].map(
                    (value) => [value, value.toUpperCase()] as [string, string],
                  ),
                ])}
                {select("assessment", "Analisi", [
                  ["", "Tutti gli esiti"],
                  ["pending", "Da analizzare"],
                  ["hard_rule", "Escluse da regola"],
                  ["semantic_not_reportable", "Non segnalabili · ChatGPT"],
                  ["reportable", "Segnalabili"],
                  ["unprojected", "Non proiettate"],
                ])}
                {select("decision", "Decisione utente", [
                  ["", "Tutte le decisioni"],
                  ["NONE", "Nessuna registrata"],
                  ...[
                    "TO_REVIEW",
                    "INTERESTED",
                    "APPLIED",
                    "NOT_INTERESTED",
                  ].map(
                    (value) =>
                      [value, labels[value] || value] as [string, string],
                  ),
                ])}
              </div>
              <div className="filter-actions">
                <button type="submit" className="primary" disabled={loading}>
                  Applica filtri
                </button>
                <button
                  type="button"
                  className="quiet"
                  onClick={() => navigate(new URLSearchParams())}
                >
                  Azzera
                </button>
              </div>
            </form>
            <div className="results-heading" role="status" aria-live="polite">
              <h2>Inventario</h2>
              <span>
                {loading
                  ? "Caricamento risultati…"
                  : page
                    ? `${new Intl.NumberFormat("it-IT").format(page.total)} opportunità corrispondenti`
                    : ""}
              </span>
            </div>
            {!loading && page && page.items.length === 0 ? (
              <div className="empty-state">
                <h3>Nessuna opportunità corrisponde ai filtri</h3>
                <p>
                  Prova un’altra ricerca o includi gli altri stati del ciclo di
                  vita.
                </p>
                <button
                  type="button"
                  onClick={() => navigate(new URLSearchParams())}
                >
                  Mostra tutto l’inventario
                </button>
              </div>
            ) : (
              <>
                <p className="mobile-hint secondary">
                  La tabella scorre orizzontalmente per mostrare tutti i campi.
                </p>
                <div
                  className="table-scroll"
                  role="region"
                  aria-label="Tabella opportunità, scorrevole orizzontalmente"
                  tabIndex={0}
                  aria-busy={loading}
                >
                  <table>
                    <caption className="sr-only">
                      Opportunità importate dallo snapshot confermato. Apri un
                      ruolo per consultare storico e provenienza.
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Ruolo / azienda</th>
                        <th scope="col">Sede / batch</th>
                        <th scope="col">Ciclo di vita</th>
                        <th scope="col">Analisi</th>
                        <th scope="col" className="numeric">
                          Fit
                        </th>
                        <th scope="col">Decisione utente</th>
                      </tr>
                    </thead>
                    <tbody>
                      {loading ? (
                        <tr>
                          <td colSpan={6} className="loading-cell">
                            Lettura delle opportunità…
                          </td>
                        </tr>
                      ) : (
                        page?.items.map((job) => (
                          <tr key={job.id}>
                            <th scope="row">
                              <button
                                type="button"
                                className="row-link"
                                onClick={() => setSelected(job)}
                                aria-label={`Apri dettagli: ${job.title || job.jobKey}`}
                              >
                                {job.title || "Titolo non disponibile"}
                              </button>
                              <span className="company-name">
                                {job.company}
                              </span>
                            </th>
                            <td>
                              {job.location || "Sede non disponibile"}
                              <span className="cell-meta">
                                {job.batch?.toUpperCase() ||
                                  "Batch non assegnato"}
                              </span>
                            </td>
                            <td>
                              <span
                                className={`status status-${job.lifecycle.toLowerCase()}`}
                              >
                                {labels[job.lifecycle]}
                              </span>
                              {job.coverage && job.coverage !== "VERIFIED" && (
                                <span className="cell-meta">
                                  Fonte{" "}
                                  {labels[job.coverage]?.toLowerCase() ||
                                    job.coverage}
                                </span>
                              )}
                            </td>
                            <td className="assessment-cell">
                              {assessment(job)}
                            </td>
                            <td className="numeric">
                              {job.fitScore === null ? (
                                <span aria-label="Punteggio non disponibile">
                                  —
                                </span>
                              ) : (
                                job.fitScore
                              )}
                            </td>
                            <td>
                              {job.decision ? (
                                <span className="decision">
                                  {labels[job.decision]}
                                </span>
                              ) : (
                                <span className="secondary">Nessuna</span>
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
                <nav className="pagination" aria-label="Paginazione risultati">
                  <span className="secondary">
                    {page && !loading
                      ? `${page.items.length} risultati in questa pagina`
                      : "Pagina in caricamento"}
                  </span>
                  <div>
                    {params.has("cursor") && (
                      <button
                        type="button"
                        onClick={() => {
                          const next = new URLSearchParams(query);
                          next.delete("cursor");
                          navigate(next);
                        }}
                        disabled={loading}
                      >
                        Prima pagina
                      </button>
                    )}
                    <button
                      type="button"
                      disabled={loading || !page?.nextCursor}
                      onClick={() => {
                        if (page?.nextCursor) {
                          const next = new URLSearchParams(query);
                          next.set("cursor", page.nextCursor);
                          navigate(next);
                        }
                      }}
                    >
                      Pagina successiva
                    </button>
                  </div>
                </nav>
              </>
            )}
          </>
        )}
      </main>
      <footer className="app-footer">
        <span>
          GitHub / Python: autorità operativa · D1: consultazione locale
        </span>
        <span>Nessun comando produttivo attivo</span>
      </footer>
      {selected && snapshot && (
        <JobDetail
          selected={selected}
          snapshotId={snapshot.id}
          commitSha={snapshot.commitSha}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
