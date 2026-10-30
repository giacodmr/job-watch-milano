import { useEffect, useRef, useState } from "react";
import { detailResponseSchema } from "../shared/queries";
import type { JobDetail as Detail, JobView } from "../shared/queries";
import { dateLabel, errorMessage, githubSource, labels, readApi } from "./api";

export default function JobDetail({
  selected,
  snapshotId,
  commitSha,
  onClose,
}: {
  selected: JobView;
  snapshotId: string;
  commitSha: string;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const element = dialog.current,
      previousFocus = document.activeElement;
    const scroll = window.scrollY;
    const body = document.body;
    const previousStyles = { position: body.style.position, top: body.style.top, width: body.style.width, overflow: body.style.overflow };
    // Lock the background while preserving the explorer's exact scroll context.
    Object.assign(body.style, { position: 'fixed', top: `-${scroll}px`, width: '100%', overflow: 'hidden' });
    element?.showModal();
    return () => {
      element?.close();
      Object.assign(body.style, previousStyles);
      window.scrollTo(0, scroll);
      if (previousFocus instanceof HTMLElement) previousFocus.focus({ preventScroll: true });
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    readApi(
      `/api/jobs/${selected.id}?snapshot=${encodeURIComponent(snapshotId)}`,
      detailResponseSchema,
      controller.signal,
    )
      .then(setDetail)
      .catch((error) => {
        if (!controller.signal.aborted) setError(errorMessage(error));
      });
    return () => controller.abort();
  }, [selected.id, snapshotId]);
  return (
    <dialog
      ref={dialog}
      className="job-dialog"
      aria-labelledby="detail-title"
      aria-describedby="detail-mode"
      onCancel={onClose}
    >
      <header className="dialog-header">
        <div>
          <p className="secondary">{selected.company}</p>
          <h2 id="detail-title">
            {selected.title || "Titolo non disponibile"}
          </h2>
        </div>
        <button type="button" onClick={onClose} className="quiet">
          Chiudi
        </button>
      </header>
      <div className="dialog-body">
        {error ? (
          <p role="alert" className="error">
            {error}
          </p>
        ) : !detail ? (
          <p role="status">Caricamento dettaglio…</p>
        ) : (
          <>
            <div className="detail-summary"><span className="inline-tag">{detail.job.fitScore == null ? 'Fit non disponibile' : `Fit ${detail.job.fitScore}`}</span><span className="inline-tag">{labels[detail.job.lifecycle]}</span><span className="inline-tag">{detail.job.decision ? labels[detail.job.decision] : 'Nessuna decisione registrata'}</span></div>
            <p className="secondary">La sintesi testuale ChatGPT, RAL e seniority strutturate non sono disponibili nel contratto di lettura attuale. Nessun valore viene stimato.</p>
            <dl className="facts">
              <div>
                <dt>Sede</dt>
                <dd>{detail.job.location || "Non disponibile"}</dd>
              </div>
              <div>
                <dt>Ciclo di vita</dt>
                <dd>{labels[detail.job.lifecycle]}</dd>
              </div>
              <div>
                <dt>Decisione utente</dt>
                <dd>
                  {detail.job.decision
                    ? labels[detail.job.decision]
                    : "Nessuna registrata"}
                </dd>
              </div>
              <div>
                <dt>Copertura fonte</dt>
                <dd>
                  {detail.job.coverage
                    ? labels[detail.job.coverage] || detail.job.coverage
                    : "Non disponibile"}
                </dd>
              </div>
              <div>
                <dt>Prima osservazione</dt>
                <dd>{dateLabel(detail.job.firstSeenAt)}</dd>
              </div>
              <div>
                <dt>Ultima osservazione</dt>
                <dd>{dateLabel(detail.job.lastSeenAt)}</dd>
              </div>
            </dl>
            {detail.job.hardExclusionReason && (
              <p className="notice">
                Esclusione da regola Python: {detail.job.hardExclusionReason}
              </p>
            )}
            {detail.job.technicalStatus && (
              <p className="notice">
                Stato tecnico:{" "}
                {labels[detail.job.technicalStatus] ||
                  detail.job.technicalStatus}
                . Un errore tecnico non costituisce una valutazione semantica.
              </p>
            )}
            <section>
              <h3>Valutazioni semantiche osservate</h3>
              <p className="secondary">
                Distinte dalle decisioni utente. Fino a 50 versioni importate in
                questa vista.
              </p>
              {detail.reviews.length ? (
                <ol className="history">
                  {detail.reviews.map((review) => (
                    <li key={review.id}>
                      <div>
                        <strong>{dateLabel(review.analyzedAt)}</strong>
                        <span>
                          {review.fitScore === null
                            ? "Fit non disponibile"
                            : `Fit ${review.fitScore}`}{" "}
                          ·{" "}
                          {review.reportable === null
                            ? "Segnalabilità non disponibile"
                            : review.reportable
                              ? "Segnalabile"
                              : "Non segnalabile"}
                        </span>
                      </div>
                      <p className="secondary">
                        {review.method}
                        {review.evidenceState === "HISTORICAL_SHORTENED"
                          ? " · Evidenza storica abbreviata"
                          : ""}
                        {review.fingerprint !== detail.job.fingerprint
                          ? " · Fingerprint precedente"
                          : ""}
                      </p>
                      <a
                        href={githubSource(review.commitSha, review.sourcePath)}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Fonte della valutazione
                      </a>
                    </li>
                  ))}
                </ol>
              ) : (
                <p>Nessuna valutazione importata per questa identità.</p>
              )}
            </section>
            <section>
              <h3>Decisioni utente osservate</h3>
              {detail.decisions.length ? (
                <ol className="history">
                  {detail.decisions.map((decision) => (
                    <li key={decision.id}>
                      <div>
                        <strong>{labels[decision.decision]}</strong>
                        <span>{dateLabel(decision.decidedAt)}</span>
                      </div>
                      {decision.rejectionReason && (
                        <p className="secondary">
                          Motivo registrato:{" "}
                          {labels[decision.rejectionReason] ||
                            decision.rejectionReason}
                        </p>
                      )}
                      <a
                        href={githubSource(
                          decision.commitSha,
                          decision.sourcePath,
                        )}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Fonte della decisione
                      </a>
                    </li>
                  ))}
                </ol>
              ) : (
                <p>Nessuna decisione importata per questa identità.</p>
              )}
            </section>
            <section className="provenance">
              <h3>Provenienza</h3>
              <p>
                <a
                  href={githubSource(commitSha, detail.job.sourcePath)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {detail.job.sourcePath}
                </a>
              </p>
              <dl>
                <dt>Chiave corrente</dt>
                <dd>
                  <code translate="no">{detail.job.jobKey}</code>
                </dd>
                <dt>Fingerprint</dt>
                <dd>
                  <code translate="no">
                    {detail.job.fingerprint || "Non disponibile"}
                  </code>
                </dd>
                <dt>SHA-256 del file</dt>
                <dd>
                  <code translate="no">{detail.job.sourceSha256}</code>
                </dd>
              </dl>
              {detail.aliases.length > 1 && (
                <details>
                  <summary>
                    Chiavi riconciliate ({detail.aliases.length})
                  </summary>
                  <ul>
                    {detail.aliases.map((alias) => (
                      <li key={alias}>
                        <code translate="no">{alias}</code>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <p className="secondary">
                Lo storico inizia dalle versioni osservate negli import.
                Motivazioni libere e job description integrali non vengono
                replicate.
              </p>
            </section>
          </>
        )}
      </div>
      <footer className="dialog-footer">
        {(selected.applyUrl || selected.canonicalUrl) ? (
          <a
            className="button-primary"
            href={selected.applyUrl || selected.canonicalUrl || undefined}
            target="_blank"
            rel="noreferrer"
          >
            Apri annuncio ufficiale
          </a>
        ) : <span className="secondary">Annuncio ufficiale non disponibile</span>}
        <div className="decision-actions" role="group" aria-label="Decisioni non disponibili in sola lettura">{['Interessante', 'Candidatura inviata', 'Da valutare', 'Scarta'].map(label => <button type="button" key={label} disabled title="Salvataggio delle decisioni non disponibile: backend comandi disabilitato">{label}</button>)}</div>
        <p className="secondary" id="detail-mode">Azioni non disponibili · Nessuna modifica operativa. Rianalisi ChatGPT, note e confronto non ancora collegati.</p>
      </footer>
    </dialog>
  );
}
