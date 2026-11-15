"""Publish only validated JobRadar JSON using native Git and Windows GCM.

No checkout, hooks, source-directory index, token handling or force push is used.
Each attempt retains its validated payload and isolated Git index for diagnosis.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from collect_jobs import ROOT
from prepare_jobradar_release import prepare

REMOTE = 'https://github.com/nihaokeaio/MyHTML.git'
TEST_BRANCH = 'codex/jobradar-git-validation'
ALLOWED = {'jobradar/jobs.json', 'jobradar/daily-summary.json'}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def guard_branch(branch, enable_main=False):
    if branch != TEST_BRANCH and not (branch == 'main' and enable_main):
        raise ValueError('Only the fixed test branch or explicitly enabled main is allowed')


class GitFailure(RuntimeError):
    def __init__(self, stage, code):
        # Raw Git output may contain credential/helper diagnostics; never log it.
        super().__init__('Git failed at ' + stage)
        self.stage, self.code = stage, code


class NativeGit:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.repo = self.directory / 'repository.git'
        self.hooks = self.directory / 'empty-hooks'
        self.hooks.mkdir()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('GIT_', 'GCM_'))}
        self.env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never',
                        GIT_INDEX_FILE=str(self.directory / 'release.index'))
        # Override obsolete manager-core config for this process only.
        self.options = ['git', '-c', 'credential.helper=', '-c', 'credential.helper=manager',
                        '-c', 'credential.interactive=never', '-c', 'core.hooksPath=' + str(self.hooks),
                        '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false',
                        '-c', 'user.name=nihaokeaio', '-c',
                        'user.email=35339142+nihaokeaio@users.noreply.github.com']
        self.run('init', ['init', '--bare', str(self.repo)], in_repo=False)

    def run(self, stage, args, data=None, in_repo=True):
        command = self.options + (['--git-dir=' + str(self.repo)] if in_repo else []) + args
        try:
            r = subprocess.run(command, input=data, capture_output=True, env=self.env,
                               cwd=self.directory, timeout=120)
        except subprocess.TimeoutExpired:
            raise GitFailure(stage, 'timeout') from None
        if r.returncode:
            raise GitFailure(stage, r.returncode)
        return r.stdout

    def head(self, remote, branch):
        rows = self.run('read_remote', ['ls-remote', '--heads', remote, 'refs/heads/' + branch])
        lines = rows.decode('ascii').splitlines()
        if not lines:
            return None
        if len(lines) != 1 or lines[0].split()[1] != 'refs/heads/' + branch:
            raise ValueError('Unexpected remote ref response')
        return lines[0].split()[0]


@contextmanager
def publication_lock(state):
    state.mkdir(parents=True, exist_ok=True)
    lock = state / 'publish.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('Publication lock exists; confirm no publisher is running before recovery') from None
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def publish(data, summary, state, branch=TEST_BRANCH, push=False, enable_main=False,
            remote=REMOTE, git_factory=NativeGit):
    """remote/git_factory are injectable for offline transport fault tests, not CLI options."""
    guard_branch(branch, enable_main)
    state = Path(state).resolve()
    with publication_lock(state):
        attempt = state / ('attempt-' + uuid.uuid4().hex)
        attempt.mkdir()
        result = {'time': utc_now(), 'branch': branch, 'result': 'failed', 'pushed': False,
                  'attempt': attempt.name}
        try:
            # Validate the actual saved bytes again to catch a concurrent collector rewrite.
            first = prepare(data, summary, attempt / 'snapshot')
            manifest = prepare(attempt / 'snapshot/jobradar/jobs.json',
                               attempt / 'snapshot/jobradar/daily-summary.json', attempt / 'payload')
            if first != manifest or set(manifest['files']) != ALLOWED:
                raise ValueError('Source changed while preparing release')
            manifest['allowed_branch'] = branch
            (attempt / 'payload/release-manifest.json').write_text(
                json.dumps(manifest, ensure_ascii=False) + '\n', encoding='utf-8')
            result.update(run_id=manifest['run_id'], files=manifest['files'], health=manifest['status'])
            git = git_factory(attempt / 'git')
            before = git.head(remote, branch)
            if before is None and branch == 'main':
                raise ValueError('Refusing to create missing main')
            base_branch = branch if before else 'main'
            base = before or git.head(remote, 'main')
            if not base:
                raise ValueError('Remote main is missing')
            git.run('fetch', ['fetch', '--no-tags', remote, 'refs/heads/' + base_branch])
            fetched = git.run('read_base', ['rev-parse', 'FETCH_HEAD']).decode().strip()
            if fetched != base:
                raise ValueError('Remote advanced during fetch; retry from latest state')
            result['before'] = base
            # Refuse stale local data even if it is within the 26-hour absolute limit.
            paths = git.run('read_paths', ['ls-tree', '-r', '--name-only', base]).decode().splitlines()
            if 'jobradar/jobs.json' in paths:
                old = json.loads(git.run('read_old_batch', ['show', base + ':jobradar/jobs.json']))
                new = json.loads((attempt / 'payload/jobradar/jobs.json').read_bytes())
                if old.get('updated_at') and datetime.fromisoformat(old['updated_at']) > datetime.fromisoformat(new['updated_at']):
                    raise ValueError('Remote batch is newer than local data')
                if old.get('updated_at') == new.get('updated_at') and old != new:
                    raise ValueError('Same-time remote batch differs; manual review required')
            git.run('read_index', ['read-tree', base])
            expected = {}
            for name in sorted(ALLOWED):
                content = (attempt / 'payload' / name).read_bytes()
                if hashlib.sha256(content).hexdigest() != manifest['files'][name]:
                    raise ValueError('Payload changed after validation')
                sha = git.run('write_blob', ['hash-object', '-w', '--stdin'], content).decode().strip()
                expected[name] = sha
                git.run('stage_allowed_blob', ['update-index', '--add', '--cacheinfo', '100644,' + sha + ',' + name])
            changed = git.run('check_allowlist', ['diff', '--cached', '--name-only', base]).decode().splitlines()
            if not set(changed) <= ALLOWED:
                raise ValueError('Commit contains non-allowlisted paths')
            result['changed_paths'] = changed
            tree = git.run('write_tree', ['write-tree']).decode().strip()
            if not push:
                result.update(result='dry_run', after=base, no_op=not changed)
                return result
            if git.head(remote, branch) != before:
                raise ValueError('Remote advanced before push; retry from latest state')
            # New test branch may point at an identical base without creating an empty commit.
            after = base
            if changed:
                after = git.run('commit_data', ['commit-tree', tree, '-p', base],
                                ('data(jobradar): publish batch ' + manifest['run_id'] + '\n').encode()).decode().strip()
            if changed or before is None:
                git.run('push', ['push', '--porcelain', remote, after + ':refs/heads/' + branch])
                result['pushed'] = True
            if git.head(remote, branch) != after:
                raise ValueError('Remote verification failed; inspect latest remote before retry')
            # Fetch and hash the bytes actually reachable through the remote branch.
            git.run('verify_fetch', ['fetch', '--no-tags', remote, 'refs/heads/' + branch])
            if git.run('verify_ref', ['rev-parse', 'FETCH_HEAD']).decode().strip() != after:
                raise ValueError('Remote advanced during verification')
            for name, sha in expected.items():
                actual = git.run('verify_blob', ['rev-parse', 'FETCH_HEAD:' + name]).decode().strip()
                if actual != sha:
                    raise ValueError('Remote file differs from validated payload')
            result.update(result='published' if result['pushed'] else 'no_op', after=after, no_op=not changed)
            return result
        except GitFailure as error:
            result.update(error='git_failure', stage=error.stage, exit_code=error.code)
            raise
        except Exception:
            # Exception strings from dependencies are deliberately excluded from logs.
            result['error'] = 'validation_or_state_failure'
            raise
        finally:
            result['finished_at'] = utc_now()
            line = json.dumps(result, ensure_ascii=False)
            (attempt / 'result.json').write_text(line + '\n', encoding='utf-8')
            with (state / 'publish.jsonl').open('a', encoding='utf-8') as log:
                log.write(line + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--branch', default=TEST_BRANCH)
    p.add_argument('--enable-main', action='store_true', help='Explicit opt-in; never needed for the test branch')
    p.add_argument('--push', action='store_true', help='Without this flag, validate and plan only')
    p.add_argument('--data', type=Path, default=ROOT / 'jobradar/jobs.json')
    p.add_argument('--summary', type=Path, default=ROOT / 'jobradar/daily-summary.json')
    p.add_argument('--state', type=Path, default=ROOT / '.jobradar-state/git-publish')
    a = p.parse_args()
    try:
        result = publish(a.data, a.summary, a.state, a.branch, a.push, a.enable_main)
    except GitFailure as e:
        print(json.dumps({'result': 'failed', 'stage': e.stage, 'exit_code': e.code,
                          'message': 'Native Git failed; payload retained. Check GCM/network, then retry.'}))
        return 1
    except Exception:
        print(json.dumps({'result': 'failed', 'message': 'Validation, branch guard or remote state check failed; no automatic conflict resolution.'}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
