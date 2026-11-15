"""Publish validated data to a test branch only. Token is read from the process environment."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from collect_jobs import ROOT
from prepare_jobradar_release import prepare

REPOSITORY='nihaokeaio/MyHTML'
TEST_BRANCH='codex/jobradar-monitor-validation'
ALLOWED={'jobradar/jobs.json','jobradar/daily-summary.json'}


def guard_branch(branch):
    if branch!=TEST_BRANCH:
        raise ValueError('This validation publisher only permits '+TEST_BRANCH+'; main and development branches are forbidden')


def blob_sha(content):
    return hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()


def plan_release(bundle,manifest,remote_blobs,branch=TEST_BRANCH):
    guard_branch(branch)
    if set(manifest['files'])!=ALLOWED:raise ValueError('Release file allowlist differs')
    changes=[]
    for name,expected in manifest['files'].items():
        content=(Path(bundle)/name).read_bytes()
        if hashlib.sha256(content).hexdigest()!=expected:raise ValueError('Release changed after validation: '+name)
        sha=blob_sha(content)
        if remote_blobs.get(name)!=sha:
            changes.append({'path':name,'mode':'100644','type':'blob','content':content.decode('utf-8')})
    return changes


class GitHubAPI:
    def __init__(self,token):self.token=token
    def call(self,method,path,payload=None):
        data=json.dumps(payload,ensure_ascii=False).encode('utf-8') if payload is not None else None
        request=Request('https://api.github.com/repos/'+REPOSITORY+path,data=data,method=method,headers={
            'Authorization':'Bearer '+self.token,'User-Agent':'JobRadar/0.1',
            'Accept':'application/vnd.github+json','Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'})
        try:
            with urlopen(request,timeout=30) as response:return json.load(response)
        except HTTPError as error:
            if error.code==404 and method=='GET':return None
            raise RuntimeError('GitHub '+method+' failed: HTTP '+str(error.code)) from None


def publish(api,bundle,manifest,branch=TEST_BRANCH,push=False):
    guard_branch(branch)
    ref_path='/git/ref/heads/'+branch
    ref=api.call('GET',ref_path)
    base=ref or api.call('GET','/git/ref/heads/main')
    if not base:raise RuntimeError('Base branch missing')
    parent=base['object']['sha']
    commit=api.call('GET','/git/commits/'+parent)
    tree=api.call('GET','/git/trees/'+commit['tree']['sha']+'?recursive=1')
    if tree.get('truncated'):raise RuntimeError('Remote tree is truncated; cannot validate file set')
    remote={e['path']:e['sha'] for e in tree['tree'] if e['type']=='blob'}
    changes=plan_release(bundle,manifest,remote,branch)
    if not push or not changes:
        return {'branch':branch,'before':parent,'after':parent,'changed_paths':[e['path'] for e in changes],
                'status':manifest['status'],'pushed':False,'no_op':not changes}
    if ref is None:api.call('POST','/git/refs',{'ref':'refs/heads/'+branch,'sha':parent})
    created_tree=api.call('POST','/git/trees',{'base_tree':commit['tree']['sha'],'tree':changes})
    created_commit=api.call('POST','/git/commits',{'message':'data(jobradar): publish validated batch '+manifest['run_id'],'tree':created_tree['sha'],'parents':[parent]})
    if api.call('GET',ref_path)['object']['sha']!=parent:raise RuntimeError('Test branch advanced; re-read before retrying')
    api.call('PATCH','/git/refs/heads/'+branch,{'sha':created_commit['sha'],'force':False})
    after=api.call('GET',ref_path)['object']['sha']
    if after!=created_commit['sha']:raise RuntimeError('Published ref did not match commit')
    return {'branch':branch,'before':parent,'after':after,'changed_paths':[e['path'] for e in changes],
            'status':manifest['status'],'pushed':True,'no_op':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--branch',default=TEST_BRANCH);parser.add_argument('--push',action='store_true')
    parser.add_argument('--bundle',default=str(ROOT/'.jobradar-state/release'))
    a=parser.parse_args();guard_branch(a.branch)
    manifest=prepare(ROOT/'jobradar/jobs.json',ROOT/'jobradar/daily-summary.json',a.bundle)
    token=os.environ.get('JOBRADAR_GITHUB_TOKEN')
    if not token:raise SystemExit('Set JOBRADAR_GITHUB_TOKEN in the process environment; no token is stored or printed')
    print(json.dumps(publish(GitHubAPI(token),a.bundle,manifest,a.branch,a.push),ensure_ascii=False))
