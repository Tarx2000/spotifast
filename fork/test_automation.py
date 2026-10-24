#!/usr/bin/env python3
"""Regression checks for release ordering and fail-closed patch application."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from prepare import stamp_version, version_for


class AutomationTests(unittest.TestCase):
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
