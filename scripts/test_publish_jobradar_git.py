"""Exercise real native Git transport against local bare repositories, not API mocks."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from publish_jobradar_git import (publish, NativeGit, GitFailure, guard_branch,
                                 publication_lock, TEST_BRANCH, ALLOWED)


def git(repo, *args, data=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    return subprocess.check_output(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                                    '-c', 'commit.gpgsign=false', '--git-dir=' + str(repo), *args],
                                   input=data, stderr=subprocess.DEVNULL, env=env)


def commit(repo, branch, files):
    r = subprocess.run(['git', '--git-dir=' + str(repo), 'rev-parse', '--verify', 'refs/heads/' + branch],
                       capture_output=True)
    parent = r.stdout.decode().strip() if r.returncode == 0 else None
    git(repo, 'read-tree', parent) if parent else git(repo, 'read-tree', '--empty')
    for name, content in files.items():
        sha = git(repo, 'hash-object', '-w', '--stdin', data=content).decode().strip()
        git(repo, 'update-index', '--add', '--cacheinfo', '100644,' + sha + ',' + name)
    tree = git(repo, 'write-tree').decode().strip()
    sha = git(repo, 'commit-tree', tree, *(['-p', parent] if parent else []), data=b'test\n').decode().strip()
    git(repo, 'update-ref', 'refs/heads/' + branch, sha)
    return sha


class NativePublisherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        self.baseline = commit(self.remote, 'main', {'index.html': b'other website stays\n'})
        self.data, self.summary = self.root / 'jobs.json', self.root / 'daily-summary.json'
        stamp = datetime.now(timezone.utc).isoformat()
        self.jobs = {'run_id': 'real-git-test', 'updated_at': stamp, 'sources_ok': 1,
                     'sources_failed': [{'source': 'blocked', 'error': '403'}],
                     'details_summary': {'ok': 1, 'failed': []}, 'jobs': []}
        self.digest = {'run_id': 'real-git-test', 'updated_at': stamp, 'status': 'partial_failure'}
        self.save()

    def save(self):
        self.data.write_text(json.dumps(self.jobs), encoding='utf-8')
        self.summary.write_text(json.dumps(self.digest), encoding='utf-8')

    def publish(self, **kwargs):
        return publish(self.data, self.summary, self.root / 'state', remote=str(self.remote), **kwargs)

    def test_partial_publish_exact_allowlist_and_repeat_no_commit(self):
        first = self.publish(push=True)
        self.assertEqual(first['result'], 'published')
        self.assertEqual(first['health'], 'partial_failure')
        manifest = json.loads((self.root / 'state' / first['attempt'] / 'payload/release-manifest.json').read_text())
        self.assertEqual(manifest['allowed_branch'], TEST_BRANCH)
        self.assertEqual(set(first['changed_paths']), ALLOWED)
        self.assertEqual(git(self.remote, 'rev-parse', 'main').decode().strip(), self.baseline)
        self.assertEqual(git(self.remote, 'show', TEST_BRANCH + ':index.html'), b'other website stays\n')
        for path in ALLOWED:
            actual = git(self.remote, 'show', TEST_BRANCH + ':' + path)
            expected = self.data if path.endswith('/jobs.json') else self.summary
            self.assertEqual(actual, expected.read_bytes())
            self.assertEqual(hashlib.sha256(actual).hexdigest(), first['files'][path])
        second = self.publish(push=True)
        self.assertEqual(second['result'], 'no_op')
        self.assertEqual(first['after'], second['after'])
        self.assertFalse(second['pushed'])

    def test_dry_run_never_creates_remote_branch(self):
        result = self.publish()
        self.assertEqual(result['result'], 'dry_run')
        refs = git(self.remote, 'for-each-ref', '--format=%(refname)').decode()
        self.assertNotIn(TEST_BRANCH, refs)

    def test_network_failure_retains_payload_and_retry_succeeds(self):
        class OfflineGit(NativeGit):
            def run(self, stage, args, *a, **kw):
                if stage == 'push':
                    raise GitFailure('push', 128)
                return super().run(stage, args, *a, **kw)
        with self.assertRaises(GitFailure):
            self.publish(push=True, git_factory=OfflineGit)
        attempts = list((self.root / 'state').glob('attempt-*'))
        self.assertEqual(len(attempts), 1)
        self.assertTrue((attempts[0] / 'payload/jobradar/jobs.json').exists())
        failed = json.loads((attempts[0] / 'result.json').read_text())
        self.assertEqual((failed['result'], failed['stage']), ('failed', 'push'))
        self.assertEqual(self.publish(push=True)['result'], 'published')

    def test_lost_push_response_safe_retry_is_no_op(self):
        class LostResponse(NativeGit):
            def run(self, stage, args, *a, **kw):
                result = super().run(stage, args, *a, **kw)
                if stage == 'push':
                    raise GitFailure(stage, 'timeout')
                return result
        with self.assertRaises(GitFailure):
            self.publish(push=True, git_factory=LostResponse)
        sha = git(self.remote, 'rev-parse', TEST_BRANCH).decode().strip()
        retry = self.publish(push=True)
        self.assertEqual(retry['result'], 'no_op')
        self.assertEqual(retry['after'], sha)

    def test_concurrent_remote_commit_is_not_overwritten(self):
        self.publish(push=True)
        remote = self.remote
        class RacingGit(NativeGit):
            def run(self, stage, args, *a, **kw):
                if stage == 'push':
                    commit(remote, TEST_BRANCH, {'dinner.html': b'someone else\n'})
                return super().run(stage, args, *a, **kw)
        self.jobs['run_id'] = self.digest['run_id'] = 'next'
        self.jobs['updated_at'] = self.digest['updated_at'] = datetime.now(timezone.utc).isoformat()
        self.save()
        with self.assertRaises(GitFailure):
            self.publish(push=True, git_factory=RacingGit)
        self.assertEqual(git(remote, 'show', TEST_BRANCH + ':dinner.html'), b'someone else\n')
        retry = self.publish(push=True)
        self.assertEqual(retry['result'], 'published')
        self.assertEqual(git(remote, 'show', TEST_BRANCH + ':dinner.html'), b'someone else\n')

    def test_older_local_batch_refused(self):
        self.publish(push=True)
        self.jobs['updated_at'] = self.digest['updated_at'] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.save()
        with self.assertRaisesRegex(ValueError, 'newer'):
            self.publish(push=True)

    def test_same_time_conflicting_data_requires_review(self):
        first = self.publish(push=True)
        self.jobs['jobs'] = [{'title': 'conflicting evidence'}]
        self.save()
        with self.assertRaisesRegex(ValueError, 'manual review'):
            self.publish(push=True)
        self.assertEqual(git(self.remote, 'rev-parse', TEST_BRANCH).decode().strip(), first['after'])

    def test_guard_freshness_batch_and_masked_failure(self):
        for b in ['main', 'refs/heads/main', 'codex/jobradar-v0.1', 'other']:
            with self.assertRaises(ValueError):
                guard_branch(b)
        guard_branch('main', enable_main=True)
        for mode in ['stale', 'mixed', 'hidden']:
            with self.subTest(mode=mode):
                jobs, digest = dict(self.jobs), dict(self.digest)
                if mode == 'stale':
                    self.jobs['updated_at'] = self.digest['updated_at'] = (datetime.now(timezone.utc) - timedelta(hours=27)).isoformat()
                elif mode == 'mixed':
                    self.digest['run_id'] = 'wrong'
                else:
                    self.digest['status'] = 'ok'
                self.save()
                with self.assertRaises(ValueError):
                    self.publish(push=True)
                self.jobs, self.digest = jobs, digest

    def test_overlapping_runs_refused(self):
        with publication_lock(self.root / 'state'):
            with self.assertRaisesRegex(ValueError, 'lock'):
                self.publish(push=True)

    def test_tampered_payload_cannot_be_pushed(self):
        class TamperGit(NativeGit):
            def __init__(self, directory):
                super().__init__(directory)
                (Path(directory).parent / 'payload/jobradar/jobs.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Payload changed'):
            self.publish(push=True, git_factory=TamperGit)
        self.assertNotIn(TEST_BRANCH, git(self.remote, 'for-each-ref').decode())

    def test_failure_logs_exclude_raw_exception_diagnostics(self):
        marker = 'fake-secret-diagnostic-never-log'
        class DiagnosticsGit(NativeGit):
            def head(self, *a):
                raise RuntimeError(marker)
        with self.assertRaises(RuntimeError):
            self.publish(push=True, git_factory=DiagnosticsGit)
        logs = (self.root / 'state/publish.jsonl').read_text()
        self.assertNotIn(marker, logs)
        record = json.loads(logs)
        self.assertEqual(record['result'], 'failed')
        self.assertEqual(record['run_id'], self.jobs['run_id'])
        self.assertEqual(set(record['files']), ALLOWED)


if __name__ == '__main__':
    unittest.main()
