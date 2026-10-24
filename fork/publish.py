#!/usr/bin/env python3
"""Publish only after every package is present; interrupted uploads stay drafts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def publish(directory, version):
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root/'fork/config.json').read_text())
    repository = config['repository']
    tag = f'v{version}'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    files = [directory/f'spotifast-v{version}-macos-arm64.dmg',
             directory/f'spotifast-v{version}-macos-arm64.zip',
             directory/'checksums.txt', directory/'checksums.txt.sig', directory/'build-source.json']
    assert all(p.is_file() for p in files)
    # Refuse a pre-existing tag that points at a different source tree.
    remote = subprocess.check_output(['git', 'ls-remote', '--tags', 'origin',
                                      f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}'], text=True).splitlines()
    if remote:
        actual = next((line.split()[0] for line in remote if line.endswith('^{}')), remote[0].split()[0])
        assert actual == commit, 'An existing tag names a different commit. Increase the personal revision.'
    state = subprocess.run(['gh', 'api', f'repos/{repository}/releases/tags/{tag}'], capture_output=True, text=True)
    if state.returncode == 0:
        release = json.loads(state.stdout)
        assert release['draft'], 'Published releases are immutable to this builder.'
        assert release['target_commitish'] == commit, 'Draft source changed. Increase the personal revision.'
    else:
        if 'HTTP 404' not in state.stderr: raise RuntimeError('Could not inspect the personal release.')
        gh('release', 'create', tag, '--repo', repository, '--draft', '--target', commit,
           '--title', f'Spotify Personal {version}', '--notes-file', str(directory/'notes.md'))
    gh('release', 'upload', tag, '--repo', repository, '--clobber', *map(str, files))
    release = json.loads(gh('api', f'repos/{repository}/releases/tags/{tag}'))
    assert release['draft']
    assets = {asset['name']: asset for asset in release['assets']}
    for file in files:
        asset = assets[file.name]
        assert asset['state'] == 'uploaded' and asset['size'] == file.stat().st_size
        # GitHub exposes a SHA-256 asset digest on supported API versions.
        if asset.get('digest'):
            assert asset['digest'] == 'sha256:' + hashlib.sha256(file.read_bytes()).hexdigest()
    gh('release', 'edit', tag, '--repo', repository, '--draft=false', '--latest')
    print(f'Published {repository} {tag} with all verified assets.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    publish(args.directory.resolve(), args.version)
