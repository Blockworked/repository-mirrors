import os
import io
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mirror


class SafetyTests(unittest.TestCase):
    def test_force_push_configuration_only_updates_selected_branch_setting(self):
        targets = object.__new__(mirror.Destinations)
        targets.gl = unittest.mock.Mock()
        targets.gl.call.return_value = {'allow_force_push': False}
        targets.allow_default_force_push({'id': 123}, 'main')
        targets.gl.call.assert_called_with('/projects/123/protected_branches/main', 'PATCH', {'allow_force_push': True})

    def test_inherited_protection_is_not_modified(self):
        targets = object.__new__(mirror.Destinations)
        targets.gl = unittest.mock.Mock()
        targets.gl.call.return_value = {'allow_force_push': False, 'inherited': True}
        with self.assertRaisesRegex(RuntimeError, 'Inherited'):
            targets.allow_default_force_push({'id': 123}, 'main')
        self.assertEqual(targets.gl.call.call_count, 1)

    def test_git_diagnostics_only_return_safe_categories(self):
        self.assertEqual(mirror.git_failure_reason('fatal: https://secret@host/private-name returned 429'), 'host rate limit reached')
        self.assertEqual(mirror.git_failure_reason('remote: cannot force push to a protected branch'), 'destination branch or tag protection rejected the update')
        self.assertNotIn('private-name', mirror.git_failure_reason('unknown failure in private-name'))

    def test_unmanaged_destination_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'refusing overwrite'):
            mirror.check_destination({'description': 'another project', 'private': False}, 'expected', False, 'Codeberg')

    def test_private_source_cannot_update_public_destination(self):
        for host, privacy in [('Codeberg', {'private': False}), ('GitLab', {'visibility': 'public'})]:
            with self.subTest(host=host), self.assertRaisesRegex(RuntimeError, 'visibility mismatch'):
                mirror.check_destination({'description': 'managed', **privacy}, 'managed', True, host)

    def test_discovery_paginates_beyond_one_hundred(self):
        client = mirror.API('https://api.github.com', 'not-a-real-token')
        with patch.object(client, 'call', side_effect=[list(range(100)), [100]]) as request:
            self.assertEqual(list(client.pages('/orgs/Blockworked/repos?type=all')), list(range(101)))
            self.assertEqual(request.call_args.args[0], '/orgs/Blockworked/repos?type=all&per_page=100&page=2')

    def test_preview_never_initializes_destinations(self):
        repo = {'name': 'demo', 'full_name': 'Blockworked/demo', 'private': True}
        with patch.dict(os.environ, {'SOURCE_GITHUB_TOKEN': 'test', 'EXCLUDE_REPOS': ''}), \
             patch.object(sys, 'argv', ['mirror.py']), \
             patch.object(mirror.API, 'pages', return_value=iter([repo])), \
             patch.object(mirror, 'Destinations') as targets, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(mirror.main(), 0)
            targets.assert_not_called()
            self.assertNotIn('Blockworked/demo', output.getvalue())
            self.assertIn('[private repository]', output.getvalue())

    def test_private_failures_do_not_disclose_repository_names(self):
        repo = {'private': True, 'full_name': 'Blockworked/secret-project'}
        error = RuntimeError('GET /projects/Blockworked/secret-project: HTTP 403')
        self.assertNotIn('secret-project', mirror.failure_message(repo, error))
        self.assertEqual(mirror.repo_label(repo), '[private repository]')


class RefIntegrationTests(unittest.TestCase):
    def test_history_force_push_pruning_and_host_ref_exclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, bare, dest = [root / name for name in ('source', 'mirror.git', 'destination.git')]
            def git(*args, cwd=None):
                return subprocess.check_output(['git', *map(str, args)], cwd=cwd, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-b', 'main', source)
            git('config', 'user.email', 'test@example.invalid', cwd=source)
            git('config', 'user.name', 'Test', cwd=source)
            git('commit', '--allow-empty', '-m', 'first', cwd=source)
            first = git('rev-parse', 'HEAD', cwd=source)
            git('branch', 'obsolete', cwd=source)
            git('tag', 'v1', cwd=source)
            git('update-ref', 'refs/pull/1/head', first, cwd=source)
            git('init', '--bare', bare)
            git('init', '--bare', '--initial-branch=main', dest)
            specs = ['+refs/heads/*:refs/heads/*', '+refs/tags/*:refs/tags/*']
            git('fetch', source, *specs, cwd=bare)
            git('push', '--prune', dest, *specs, cwd=bare)
            self.assertEqual(git('rev-parse', 'refs/tags/v1', cwd=dest), first)
            self.assertNotIn('refs/pull/', git('show-ref', cwd=dest))
            git('branch', '-D', 'obsolete', cwd=source)
            git('tag', '-d', 'v1', cwd=source)
            git('checkout', '--orphan', 'replacement', cwd=source)
            git('commit', '--allow-empty', '-m', 'rewritten', cwd=source)
            rewritten = git('rev-parse', 'HEAD', cwd=source)
            git('branch', '-f', 'main', rewritten, cwd=source)
            git('fetch', '--prune', source, *specs, cwd=bare)
            git('push', '--prune', dest, *specs, cwd=bare)
            refs = git('show-ref', cwd=dest)
            self.assertEqual(git('rev-parse', 'refs/heads/main', cwd=dest), rewritten)
            self.assertNotIn('refs/heads/obsolete', refs)
            self.assertNotIn('refs/tags/v1', refs)


if __name__ == '__main__':
    unittest.main()
