import type { SnapshotView } from '../shared/queries';
import { dateLabel } from './api';

export default function SnapshotInfo({ snapshot }: { snapshot: SnapshotView }) {
  return <details className="sync-details"><summary>Provenienza e stato della pipeline</summary><dl className="facts">
    <div><dt>Commit sorgente</dt><dd><a href={`https://github.com/giacodmr/job-watch-milano/commit/${snapshot.commitSha}`} target="_blank" rel="noreferrer"><code translate="no">{snapshot.commitSha.slice(0,12)}</code></a></dd></div>
    <div><dt>Revisione locale</dt><dd>{snapshot.revision}</dd></div>
    <div><dt>Import confermato</dt><dd>{dateLabel(snapshot.confirmedAt)}</dd></div>
    <div><dt>Fonti dal</dt><dd>{dateLabel(snapshot.oldestSourceAt)}</dd></div>
    <div><dt>Raccolta</dt><dd>{snapshot.collectionStatus || 'Non disponibile'}</dd></div>
    <div><dt>Certificazione</dt><dd>{snapshot.healthStatus || 'Non disponibile'}</dd></div>
    <div><dt>Daily completo</dt><dd>{snapshot.dailyComplete == null ? 'Non disponibile' : snapshot.dailyComplete ? 'Sì' : 'No'}</dd></div>
    <div><dt>Semantica completa</dt><dd>{snapshot.fullSemanticComplete == null ? 'Non disponibile' : snapshot.fullSemanticComplete ? 'Sì' : 'No'}</dd></div>
  </dl><p className="secondary">Stati osservati nelle fonti Python a questo commit. Il controllo API e l’import locale non certificano una pipeline live.</p></details>;
}
