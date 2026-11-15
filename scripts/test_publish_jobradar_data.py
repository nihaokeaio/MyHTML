import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from publish_jobradar_data import guard_branch,plan_release,publish,TEST_BRANCH,blob_sha

class API:
    def __init__(self,remote):self.remote=remote;self.calls=[];self.head='old';self.commit_count=0
    def call(self,method,path,payload=None):
        self.calls.append((method,path))
        if method=='GET' and path.startswith('/git/ref/'):return {'object':{'sha':self.head}}
        if method=='GET' and path.startswith('/git/commits/'):return {'tree':{'sha':'tree'}}
        if method=='GET' and path.startswith('/git/trees/'):return {'tree':[{'path':p,'sha':sha,'type':'blob'} for p,sha in self.remote.items()]}
        if method=='POST' and path=='/git/trees':return {'sha':'new-tree'}
        if method=='POST' and path=='/git/commits':self.commit_count+=1;return {'sha':'new'}
        if method=='PATCH':self.head=payload['sha'];return {}
        raise AssertionError((method,path))

class PublishTests(unittest.TestCase):
    def fixture(self,root):
        files={}
        for name in ('jobradar/jobs.json','jobradar/daily-summary.json'):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'{"valid":true}\n');files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        return {'files':files,'run_id':'r','status':'partial_failure'}
    def test_main_and_development_branch_forbidden(self):
        for name in ('main','refs/heads/main','codex/jobradar-v0.1'):
            with self.assertRaises(ValueError):guard_branch(name)
    def test_two_file_plan_and_partial_failure_can_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.fixture(root);api=API({'index.html':'unchanged'})
            result=publish(api,root,manifest,push=True)
            self.assertTrue(result['pushed']);self.assertEqual(set(result['changed_paths']),set(manifest['files']))
            self.assertEqual(result['status'],'partial_failure');self.assertEqual(api.commit_count,1)
    def test_identical_data_creates_no_commit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.fixture(root);api=API({p:blob_sha((root/p).read_bytes()) for p in manifest['files']})
            result=publish(api,root,manifest,push=True)
            self.assertTrue(result['no_op']);self.assertEqual(api.commit_count,0)
            self.assertTrue(all(method=='GET' for method,_ in api.calls))
    def test_tampered_bundle_and_extra_files_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=self.fixture(root)
            (root/'jobradar/jobs.json').write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed after'):plan_release(root,manifest,{})
            manifest['files']['.env']='secret'
            with self.assertRaisesRegex(ValueError,'allowlist'):plan_release(root,manifest,{})

if __name__=='__main__':unittest.main()
