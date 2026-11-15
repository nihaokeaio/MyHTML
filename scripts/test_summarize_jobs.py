import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from summarize_jobs import build_summary
from prepare_jobradar_release import prepare


def batch(fields=None, deadline=None, stamp='2026-11-15T01:00:00+00:00'):
    return {'updated_at':stamp,'sources_ok':1,'sources_failed':[], 'details_summary':{'ok':1,'failed':[]},'jobs':[{
        'id':'notice','source':'Official','source_id':'s','url':'https://example.com/notice','last_seen':stamp,'notice_type':'招聘公告','deadline':deadline,
        'detail':{'status':'ok'},'body_positions':[{'url':'https://example.com/a','fields':fields or {'name':'C++工程师','requirements':'C++ Qt软件开发','education':'硕士及以上'},'screening':{'verdict':'需要人工核实'}}]}]}


class SummaryTests(unittest.TestCase):
    def test_new_then_identical_and_timestamp_only(self):
        first,_=build_summary({'jobs':[]},batch(),today='2026-11-15');self.assertEqual(len(first['new_positions']),1)
        second,_=build_summary(batch(),batch(stamp='2026-11-15T02:00:00+00:00'),today='2026-11-15')
        self.assertEqual(second['message'],'本次无新增重点候选');self.assertEqual(second['changed_positions'],[])
    def test_substantive_and_deadline_changes(self):
        before=batch(deadline='2026-11-20');after=deepcopy(before)
        after['jobs'][0]['body_positions'][0]['fields']['requirements']='C++ Qt OpenGL 三维可视化'
        after['jobs'][0]['deadline']='2026-11-30'
        result,_=build_summary(before,after,today='2026-11-15')
        self.assertEqual(len(result['changed_positions']),1);self.assertEqual(len(result['deadline_changed_ids']),1)
    def test_newly_confirmed_deadline_is_not_claimed_official_revision(self):
        before=batch();after=batch(deadline='2026-12-01')
        result,_=build_summary(before,after,today='2026-11-15')
        self.assertEqual(result['deadline_changed_ids'],[])
        self.assertEqual(result['changed_positions'][0]['changes'][0]['kind'],'deadline_confirmed')
    def test_whitespace_does_not_notify(self):
        before=batch();after=deepcopy(before);after['jobs'][0]['body_positions'][0]['fields']['requirements']=' C++   Qt软件开发 '
        self.assertEqual(build_summary(before,after,today='2026-11-15')[0]['changed_positions'],[])
    def test_suppression_process_expired_degree_and_outside_region(self):
        for mode in ('process','expired','degree','region'):
            after=batch()
            if mode=='process':after['jobs'][0]['notice_type']='录用公示/考察'
            if mode=='expired':after['jobs'][0]['deadline']='2020-01-01'
            if mode=='degree':after['jobs'][0]['body_positions'][0]['screening']['verdict']='明确不符合'
            if mode=='region':after['jobs'][0]['body_positions'][0]['fields']['location']='北京'
            result,_=build_summary({'jobs':[]},after,today='2026-11-15')
            self.assertEqual(result['new_positions'],[],mode)
    def test_failure_and_recovery_do_not_renotify_old_role(self):
        before=batch();failed=batch();failed['jobs'][0]['detail']['status']='failed'
        failed['details_summary']['failed']=[{'error':'403'}]
        result,memory=build_summary(before,failed,today='2026-11-15');self.assertEqual(result['status'],'partial_failure')
        recovered,_=build_summary(failed,batch(),memory,today='2026-11-15')
        self.assertEqual(recovered['new_positions'],[])
    def test_unseen_old_roles_are_not_current_observations(self):
        after=batch();after['jobs'][0]['last_seen']='yesterday'
        self.assertEqual(build_summary({'jobs':[]},after,today='2026-11-15')[0]['new_positions'],[])
    def test_expired_change_remains_auditable_but_not_default(self):
        before=batch(deadline='2026-12-01');after=batch(deadline='2026-11-01')
        result,_=build_summary(before,after,today='2026-11-15')
        self.assertEqual(result['changed_positions'],[]);self.assertEqual(len(result['suppressed_changes']),1)
    def test_ambiguous_duplicate_roles_are_not_recommended(self):
        data=batch();other=deepcopy(data['jobs'][0]['body_positions'][0]);other['fields']['education']='博士'
        data['jobs'][0]['body_positions'].append(other)
        self.assertEqual(build_summary({'jobs':[]},data,today='2026-11-15')[0]['new_positions'],[])
    def test_release_checks_batch_identity_and_does_not_hide_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=batch();data['run_id']='r';data['sources_failed']=[{'source':'bad'}]
            summary,_=build_summary({'jobs':[]},data,today='2026-11-15')
            (root/'jobs.json').write_text(json.dumps(data));(root/'summary.json').write_text(json.dumps(summary))
            manifest=prepare(root/'jobs.json',root/'summary.json',root/'release',now=datetime(2026,11,15,2,tzinfo=timezone.utc));self.assertFalse(manifest['pushed']);self.assertEqual(manifest['status'],'partial_failure')
            summary['status']='ok';(root/'summary.json').write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError,'masks'):prepare(root/'jobs.json',root/'summary.json',root/'bad',now=datetime(2026,11,15,2,tzinfo=timezone.utc))
            summary['run_id']='old';(root/'summary.json').write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError,'different batches'):prepare(root/'jobs.json',root/'summary.json',root/'bad',now=datetime(2026,11,15,2,tzinfo=timezone.utc))

    def test_all_failed_is_never_healthy_even_without_cli_codes(self):
        result,_=build_summary({'jobs':[]},{'jobs':[],'sources_ok':0},today='2026-11-15')
        self.assertEqual(result['status'],'partial_failure')
        self.assertEqual(result['message'],'本次无新增重点候选')

    def test_release_refuses_stale_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=batch();data['run_id']='r'
            summary,_=build_summary({'jobs':[]},data,today='2026-11-15')
            (root/'jobs.json').write_text(json.dumps(data));(root/'summary.json').write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError,'stale'):
                prepare(root/'jobs.json',root/'summary.json',root/'release',now=datetime(2026,11,17,tzinfo=timezone.utc))

if __name__=='__main__':unittest.main()
