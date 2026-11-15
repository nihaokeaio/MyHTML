"""Prepare only validated public data for a later test-branch publication. Never pushes."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from collect_jobs import ROOT
from summarize_jobs import atomic_json


def prepare(data, summary, output, now=None):
    data=Path(data);summary=Path(summary);output=Path(output)
    jobs=json.loads(data.read_text(encoding='utf-8'))
    digest=json.loads(summary.read_text(encoding='utf-8'))
    if not jobs.get('run_id') or digest.get('run_id')!=jobs['run_id'] or digest.get('updated_at')!=jobs.get('updated_at'):
        raise ValueError('Data and summary are stale or from different batches')
    age=((now or datetime.now(timezone.utc))-datetime.fromisoformat(jobs['updated_at'])).total_seconds()
    if age > 26*3600 or age < -300: raise ValueError('Batch is stale or computer clock differs; regenerate before publication')
    if jobs.get('sources_ok',0)<1 or jobs.get('details_summary',{}).get('ok',0)<1:
        raise ValueError('No successful collection/detail result to publish')
    if digest.get('status') not in ('ok','partial_failure'): raise ValueError('Invalid health status')
    if (jobs.get('sources_failed') or jobs.get('details_summary',{}).get('failed') or jobs.get('attachment_failures')) and digest['status']=='ok':
        raise ValueError('Summary masks recorded collection failures')
    # Explicit allowlist, no dirty working tree, source files, credentials or local notes.
    output.mkdir(parents=True,exist_ok=True)
    files={}
    for name,source in [('jobradar/jobs.json',data),('jobradar/daily-summary.json',summary)]:
        target=output/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
        files[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    manifest={'run_id':jobs['run_id'],'status':digest['status'],'files':files,'pushed':False,'allowed_branch':'codex/jobradar-monitor-validation'}
    atomic_json(output/'release-manifest.json',manifest)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',default=str(ROOT/'jobradar/jobs.json'))
    parser.add_argument('--summary',default=str(ROOT/'jobradar/daily-summary.json'))
    parser.add_argument('--output',required=True)
    a=parser.parse_args();print(json.dumps(prepare(a.data,a.summary,a.output),ensure_ascii=False))
