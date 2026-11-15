"""One local batch: collection, enrichment, delta summary; no scheduling or push."""
import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from collect_jobs import ROOT, DATA, SOURCES, log
from summarize_jobs import atomic_json, build_summary


def main(data_path=DATA, sources_path=SOURCES, state_dir=None, summary_path=None):
    data_path=Path(data_path);sources_path=Path(sources_path)
    state_dir=Path(state_dir or ROOT/'.jobradar-state')
    summary_path=Path(summary_path or ROOT/'jobradar/daily-summary.json')
    state_dir.mkdir(parents=True,exist_ok=True)
    lock=state_dir/'run.lock'
    try:
        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        log('run_blocked',error='Existing run.lock; verify no batch is running before manual recovery')
        return 1
    os.close(fd)
    try:
        previous=json.loads(data_path.read_text(encoding='utf-8')) if data_path.exists() else {'jobs':[]}
        memory_path=state_dir/'observed-positions.json'
        memory=json.loads(memory_path.read_text(encoding='utf-8')) if memory_path.exists() else {}
        atomic_json(state_dir/'previous-jobs.json',previous)
        run_id=str(uuid.uuid4());env={**os.environ,'JOBRADAR_RUN_ID':run_id}
        codes={}
        for script in ('collect_jobs.py','enrich_jobs.py'):
            result=subprocess.run([sys.executable,str(ROOT/'scripts'/script),'--data',str(data_path),'--sources',str(sources_path)],env=env,check=False)
            codes[script]=result.returncode
        current=json.loads(data_path.read_text(encoding='utf-8'))
        if current.get('run_id')!=run_id:
            log('batch_failed',error='Collector did not persist this batch; no stale summary published',stage_exit_codes=codes)
            return 1
        summary,observed=build_summary(previous,current,memory,codes)
        atomic_json(summary_path,summary)
        atomic_json(memory_path,observed)
        log('batch_complete',run_id=run_id,status=summary['status'],new=len(summary['new_positions']),changed=len(summary['changed_positions']))
        return 1 if summary['status']!='ok' else 0
    finally:
        lock.unlink()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',default=str(DATA));parser.add_argument('--sources',default=str(SOURCES))
    parser.add_argument('--state-dir');parser.add_argument('--summary')
    args=parser.parse_args()
    raise SystemExit(main(args.data,args.sources,args.state_dir,args.summary))
