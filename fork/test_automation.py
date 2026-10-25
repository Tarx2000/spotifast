#!/usr/bin/env python3
"""Regression checks for release ordering and fail-closed patch application."""
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
import contextlib
import io
from unittest.mock import patch

from prepare import stamp_version, version_for
from publish import find_release, release_by_id, validate_assets, publish


class AutomationTests(unittest.TestCase):
    def test_draft_releases_are_found_by_listing_instead_of_the_published_tag_endpoint(self):
        draft = {'id': 12, 'tag_name': 'v0.14.1001', 'draft': True}
        with patch('publish.gh', return_value=json.dumps([[], [draft]])) as request:
            self.assertEqual(find_release('owner/repo', 'v0.14.1001'), draft)
            request.assert_called_once_with('api', '--paginate', '--slurp', '-H', 'Cache-Control: no-cache',
                                            'repos/owner/repo/releases')

    def test_new_draft_publishes_even_when_the_release_list_remains_stale(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            version = '0.14.1002'
            files = [directory/f'spotifast-v{version}-macos-arm64.dmg',
                     directory/f'spotifast-v{version}-macos-arm64.zip',
                     directory/'checksums.txt', directory/'checksums.txt.sig', directory/'build-source.json']
            for file in files: file.write_bytes(b'checked fixture')
            (directory/'notes.md').write_text('Two lines\nwith a literal \\ escape.')
            commit = 'a' * 40
            release = {'id': 77, 'draft': True, 'tag_name': f'v{version}',
                       'target_commitish': commit, 'assets': []}
            lists = 0
            published = False

            def fake_git(args, **kwargs):
                if args == ['git', 'rev-parse', 'HEAD']: return commit
                if args[:2] == ['git', 'ls-remote']: return ''
                self.fail(f'Unexpected process: {args}')

            def fake_gh(*args, stdin_text=None):
                nonlocal lists, published
                if '--paginate' in args:
                    lists += 1
                    return '[[]]'  # The new draft never appears in this cached list.
                if args[:3] == ('api', '--method', 'POST'):
                    payload = json.loads(stdin_text)
                    self.assertEqual(payload['target_commitish'], commit)
                    self.assertEqual(payload['body'], (directory/'notes.md').read_text())
                    self.assertTrue(payload['draft'])
                    return json.dumps(release)
                if args[:2] == ('release', 'upload'):
                    release['assets'] = [
                        {'name': p.name, 'state': 'uploaded', 'size': p.stat().st_size,
                         'digest': 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p in files]
                    return ''
                if args[0] == 'api' and args[-1].endswith('/releases/77'):
                    return json.dumps(release)
                if args[:2] == ('release', 'edit'):
                    self.assertEqual(len(release['assets']), 5)
                    self.assertIn('--draft=false', args)
                    published = True
                    return ''
                self.fail(f'Unexpected GitHub request: {args}')

            with patch('publish.gh', side_effect=fake_gh), \
                 patch('publish.subprocess.check_output', side_effect=fake_git), \
                 contextlib.redirect_stdout(io.StringIO()):
                publish(directory, version)
            self.assertTrue(published)
            self.assertEqual(lists, 1, 'The creation response must replace a second list lookup.')

    def test_a_new_draft_id_retries_only_transient_not_found_responses(self):
        missing = subprocess.CalledProcessError(1, ['gh'], stderr='gh: Not Found (HTTP 404)')
        with patch('publish.gh', side_effect=[missing, '{"id": 77}']), patch('publish.time.sleep') as wait:
            self.assertEqual(release_by_id('owner/repo', 77), {'id': 77})
            wait.assert_called_once_with(1)
        denied = subprocess.CalledProcessError(1, ['gh'], stderr='gh: Forbidden (HTTP 403)')
        with patch('publish.gh', side_effect=denied) as request, patch('publish.time.sleep') as wait:
            with self.assertRaises(subprocess.CalledProcessError): release_by_id('owner/repo', 77)
            self.assertEqual(request.call_count, 1)
            wait.assert_not_called()

    def test_incomplete_or_modified_assets_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as name:
            package = Path(name)/'package.zip'
            package.write_bytes(b'checked package')
            asset = {'name': package.name, 'state': 'uploaded', 'size': package.stat().st_size,
                     'digest': 'sha256:' + hashlib.sha256(package.read_bytes()).hexdigest()}
            validate_assets([package], {'assets': [asset]})
            with self.assertRaises(KeyError): validate_assets([package], {'assets': []})
            for change in [{'state': 'new'}, {'size': 0}, {'digest': 'sha256:' + '0' * 64}]:
                with self.assertRaises(AssertionError): validate_assets([package], {'assets': [asset | change]})

    def test_upstream_and_personal_updates_have_distinct_ordered_versions(self):
        tags = ['v0.14.1', 'v0.14.2', 'v0.15.0', 'v1.0.0']
        versions = [tuple(map(int, version_for(t, 1).split('.'))) for t in tags]
        self.assertEqual(versions, sorted(versions))
        self.assertLess(version_for('v0.14.1', 1), version_for('v0.14.1', 2))
        for tag in ['main', 'v0.14.2-rc1', '../v1.0.0', 'v1.0.0+custom']:
            with self.assertRaises(ValueError): version_for(tag, 1)

    def test_lockfile_changes_only_the_root_package(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            (p/'Cargo.toml').write_text('[package]\nname = "spotifast"\nversion = "0.14.1"\n')
            (p/'Cargo.lock').write_text('[[package]]\nname = "other"\nversion = "0.14.1"\n\n[[package]]\nname = "spotifast"\nversion = "0.14.1"\n')
            stamp_version(p, '0.14.1001')
            self.assertIn('name = "other"\nversion = "0.14.1"', (p/'Cargo.lock').read_text())
            self.assertIn('name = "spotifast"\nversion = "0.14.1001"', (p/'Cargo.lock').read_text())

    def test_conflicting_upstream_changes_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            p = Path(name)
            subprocess.run(['git', 'init', '-q', str(p)], check=True)
            (p/'source.txt').write_text('a changed upstream implementation\n')
            patch = b'diff --git a/source.txt b/source.txt\n--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-original implementation\n+personal implementation\n'
            check = subprocess.run(['git', 'apply', '--check', '-'], cwd=p, input=patch, capture_output=True)
            self.assertNotEqual(check.returncode, 0)
            self.assertEqual((p/'source.txt').read_text(), 'a changed upstream implementation\n')


if __name__ == '__main__': unittest.main()
