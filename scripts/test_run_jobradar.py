import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import run_jobradar as runner

class PipelineTests(unittest.TestCase):
    def run_case(self,codes):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'jobs.json';sources=root/'sources.json'
            data.write_text(json.dumps({'jobs':[]}));sources.write_text('{"sources":[]}')
            def stage(command,env,check):
                current=json.loads(data.read_text())
                current.update({'run_id':env['JOBRADAR_RUN_ID'],'updated_at':'2026-11-15T01:00:00+00:00','sources_ok':1,'sources_failed':[],'details_summary':{'ok':1,'failed':[]}})
                data.write_text(json.dumps(current));return SimpleNamespace(returncode=codes.pop(0))
            with patch.object(runner.subprocess,'run',side_effect=stage) as call:
                code=runner.main(data,sources,root/'state',root/'summary.json')
            return code,call.call_count,json.loads((root/'summary.json').read_text())
    def test_collection_failure_still_enriches_and_fails(self):
        code,count,result=self.run_case([1,0]);self.assertEqual(code,1);self.assertEqual(count,2);self.assertEqual(result['status'],'partial_failure')
    def test_detail_failure_is_not_hidden(self):self.assertEqual(self.run_case([0,1])[0],1)
    def test_both_successful(self):self.assertEqual(self.run_case([0,0])[0],0)
    def test_lock_prevents_overlapping_runs(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder);(state/'run.lock').write_text('running')
            with patch.object(runner.subprocess,'run') as call:
                self.assertEqual(runner.main(state_dir=state),1);call.assert_not_called()

if __name__=='__main__':unittest.main()
