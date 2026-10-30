"""Child process only: hash real pure projections in an isolated Git archive."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
import os
import sys


def main():
    root, at = Path(sys.argv[1]), sys.argv[2]
    sys.dont_write_bytecode = True
    sys.path.insert(0,str(root))
    def blocked(*args, **kwargs): raise RuntimeError('NETWORK_DISABLED')
    socket.socket = blocked; socket.create_connection = blocked
    subprocess.Popen = blocked
    os.system = blocked
    def hash_json(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    def files():
        return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    before = files()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import pipeline_state as ps
        import job_memory
        import sync_analysis_state as projection
        import daily_worklist as daily
        import location_policy
        import collection_freshness
        for module in (ps,job_memory,projection,daily,location_policy): module.ROOT = root
        ps.now = lambda: at
        daily.now = lambda: at
        result = {'snapshot':hash_json(ps.snapshot(root)), 'batches':{}}
        for batch in ps.BATCHES:
            state = projection.project_batch(batch,root,at=at)
            memory = job_memory.load_memory(batch,root)
            result['batches'][batch] = {'projection':hash_json(state), 'queue':hash_json(state['queue']), 'memory':hash_json(memory)}
        result['daily'] = hash_json(daily.build_worklist(at=at))
        result['worker_snapshot_ready'] = collection_freshness.worker_snapshot_ready(root,at)
    if files() != before: raise RuntimeError('ISOLATED_SOURCE_MUTATED')
    print(json.dumps(result,sort_keys=True))

if __name__ == '__main__':
    try: main()
    except Exception:
        print('{"error":"ENGINE_PROBE_FAILED"}')
        sys.exit(1)
