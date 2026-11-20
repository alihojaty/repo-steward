import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'inspect_repo.py'


class InspectorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.repo = self.home / 'repo'
        self.repo.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(
            HOME=str(self.home),
            XDG_CONFIG_HOME=str(self.home),
            GIT_CONFIG_NOSYSTEM='1',
            GIT_AUTHOR_NAME='Test',
            GIT_AUTHOR_EMAIL='test@example.invalid',
            GIT_COMMITTER_NAME='Test',
            GIT_COMMITTER_EMAIL='test@example.invalid',
        )
        self.git('init', '-q')

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(
            ['git', *args],
            cwd=cwd or self.repo,
            env=self.env,
            capture_output=True,
            check=check,
        )

    def run_helper(self, path=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), '--repo', str(path or self.repo)],
            env=self.env,
            capture_output=True,
        )

    def info(self, path=None):
        p = self.run_helper(path)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def baseline(self):
        (self.repo / 'source').write_text('initial\n')
        self.git('add', 'source')
        self.git('commit', '-qm', 'baseline')

    def test_unborn(self):
        data = self.info()
        self.assertEqual(data['head_state'], 'unborn')
        self.assertIsNone(data['head'])
        self.assertTrue(data['is_worktree_root'])
        self.assertFalse(data['is_shallow'])

    def test_mixed_preserves_index_and_worktree(self):
        self.baseline()
        src = self.repo / 'source'
        src.write_text('stage\n')
        self.git('add', 'source')
        src.write_text('not staged\n')
        (self.repo / 'odd\nname').touch()
        index = self.repo / '.git' / 'index'
        before = index.read_bytes()
        self.assertEqual(
            self.info()['counts'],
            dict(staged=1, unstaged=1, unmerged=0, untracked_entries=1, submodule_changes=0),
        )
        self.assertEqual(before, index.read_bytes())
        self.assertEqual(src.read_text(), 'not staged\n')

    def test_subdir_worktree_root_flag_without_path_leak(self):
        self.baseline()
        sub = self.repo / 'secret-subdir-name'
        sub.mkdir()
        p = self.run_helper(sub)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(b'secret-subdir-name', p.stdout + p.stderr)
        data = json.loads(p.stdout)
        self.assertFalse(data['is_worktree_root'])

    def test_detached_and_linked_worktree(self):
        self.baseline()
        linked = self.home / 'linked'
        self.git('worktree', 'add', '-q', '--detach', str(linked), 'HEAD')
        self.assertEqual(self.info(linked)['head_state'], 'detached')
        self.assertEqual(self.info()['head_state'], 'attached')

    def test_conflict_and_operation_markers(self):
        self.baseline()
        start = self.git('symbolic-ref', '--short', 'HEAD').stdout.decode().strip()
        self.git('checkout', '-qb', 'alternate-change')
        (self.repo / 'source').write_text('alternate\n')
        self.git('commit', '-qam', 'alternate')
        self.git('checkout', '-q', start)
        (self.repo / 'source').write_text('different\n')
        self.git('commit', '-qam', 'different')
        self.assertNotEqual(self.git('merge', 'alternate-change', check=False).returncode, 0)
        data = self.info()
        self.assertIn('MERGE_HEAD', data['operations'])
        self.assertEqual(data['counts']['unmerged'], 1)

    def test_lock_and_rebase_markers_detected(self):
        self.baseline()
        gitdir = self.repo / '.git'
        (gitdir / 'index.lock').touch()
        (gitdir / 'HEAD.lock').touch()
        (gitdir / 'rebase-merge').mkdir()
        (gitdir / 'CHERRY_PICK_HEAD').touch()
        ops = set(self.info()['operations'])
        self.assertTrue({'index.lock', 'HEAD.lock', 'rebase-merge', 'CHERRY_PICK_HEAD'}.issubset(ops))

    def test_shallow_clone_detected(self):
        self.baseline()
        (self.repo / 'source').write_text('second\n')
        self.git('commit', '-qam', 'second')
        shallow = self.home / 'shallow'
        self.git('clone', '-q', '--depth=1', f'file://{self.repo}', str(shallow), cwd=self.home)
        self.assertTrue(self.info(shallow)['is_shallow'])

    def test_signing_config_detected_without_key_leak(self):
        self.baseline()
        self.git('config', 'commit.gpgsign', 'true')
        self.git('config', 'user.signingkey', 'SENSITIVE_KEY_ID_999')
        p = self.run_helper()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(b'SENSITIVE_KEY_ID_999', p.stdout + p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data['signing_configured'], {'commit': True, 'tag': False})

    def test_dirty_submodule_counted_separately(self):
        sub_origin = self.home / 'sub-origin'
        sub_origin.mkdir()
        self.git('init', '-q', cwd=sub_origin)
        (sub_origin / 'lib.txt').write_text('v1\n')
        self.git('add', 'lib.txt', cwd=sub_origin)
        self.git('commit', '-qm', 'init sub', cwd=sub_origin)

        self.baseline()
        self.git('-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(sub_origin), 'vendor/lib')
        self.git('commit', '-qm', 'add submodule')
        (self.repo / 'vendor' / 'lib' / 'lib.txt').write_text('dirty\n')

        counts = self.info()['counts']
        self.assertEqual(counts['submodule_changes'], 1)
        self.assertEqual(counts['unstaged'], 1)

    def test_no_disclosure(self):
        self.git('remote', 'add', 'origin', 'https://user:dummy-token@example.invalid/repo')
        (self.repo / 'private-filename').touch()
        p = self.run_helper()
        self.assertEqual(p.returncode, 0)
        for needle in (b'dummy-token', b'private-filename', b'example.invalid'):
            self.assertNotIn(needle, p.stdout + p.stderr)

    def test_outside_worktree(self):
        self.assertEqual(self.run_helper(self.home).returncode, 2)

    def test_bare(self):
        bare = self.home / 'bare'
        self.git('init', '--bare', str(bare))
        self.assertEqual(self.run_helper(bare).returncode, 2)

    def test_overrides_rejected(self):
        for var, val in (
            ('GIT_INDEX_FILE', str(self.home / 'other')),
            ('GIT_CONFIG_PARAMETERS', "'core.bare=true'"),
            ('GIT_CONFIG', str(self.home / 'custom.cfg')),
        ):
            with self.subTest(var=var):
                old = self.env.get(var)
                self.env[var] = val
                try:
                    self.assertEqual(self.run_helper().returncode, 2)
                finally:
                    if old is None:
                        self.env.pop(var, None)
                    else:
                        self.env[var] = old


if __name__ == '__main__':
    unittest.main()
