#!/usr/bin/env python3
"""Publish only after every package is present; interrupted uploads stay drafts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def gh(*args, stdin_text=None):
    return subprocess.check_output(['gh', *args], input=stdin_text, text=True, stderr=subprocess.PIPE)


def find_release(repository, tag):
    # GitHub's release-by-tag endpoint returns 404 for a draft. Listing releases
    # with the publishing token includes drafts and gives their stable REST ID.
    pages = json.loads(gh('api', '--paginate', '--slurp', '-H', 'Cache-Control: no-cache',
                          f'repos/{repository}/releases'))
    matches = [release for page in pages for release in page if release['tag_name'] == tag]
    assert len(matches) <= 1, 'Ambiguous release tag.'
    return matches[0] if matches else None


def create_draft(repository, tag, commit, version, notes):
    # Use the POST response's ID directly. An immediately repeated list request
    # can still omit the new draft even though creation succeeded.
    payload = {'tag_name': tag, 'target_commitish': commit, 'draft': True,
               'prerelease': False, 'name': f'Spotify Personal {version}', 'body': notes}
    release = json.loads(gh('api', '--method', 'POST', f'repos/{repository}/releases',
                            '--input', '-', stdin_text=json.dumps(payload)))
    assert release['draft'] and release['tag_name'] == tag
    assert release['target_commitish'] == commit
    assert isinstance(release['id'], int)
    return release


def release_by_id(repository, release_id):
    for attempt in range(4):
        try:
            return json.loads(gh('api', '-H', 'Cache-Control: no-cache',
                                 f'repos/{repository}/releases/{release_id}'))
        except subprocess.CalledProcessError as error:
            if attempt == 3 or 'HTTP 404' not in (error.stderr or ''):
                raise
            time.sleep(2 ** attempt)


def validate_assets(files, release):
    assets = {asset['name']: asset for asset in release['assets']}
    for file in files:
        asset = assets[file.name]
        assert asset['state'] == 'uploaded' and asset['size'] == file.stat().st_size
        if asset.get('digest'):
            assert asset['digest'] == 'sha256:' + hashlib.sha256(file.read_bytes()).hexdigest()


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
    release = find_release(repository, tag)
    if release:
        assert release['draft'], 'Published releases are immutable to this builder.'
        assert release['target_commitish'] == commit, 'Draft source changed. Increase the personal revision.'
    else:
        release = create_draft(repository, tag, commit, version, (directory/'notes.md').read_text())
    release_id = release['id']
    try:
        validate_assets(files, release)
    except (KeyError, AssertionError):
        gh('release', 'upload', tag, '--repo', repository, '--clobber', *map(str, files))
    release = release_by_id(repository, release_id)
    assert release['draft']
    assert release['tag_name'] == tag and release['target_commitish'] == commit
    validate_assets(files, release)
    gh('release', 'edit', tag, '--repo', repository, '--draft=false', '--latest')
    print(f'Published {repository} {tag} with all verified assets.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    try:
        publish(args.directory.resolve(), args.version)
    except subprocess.CalledProcessError as error:
        raise SystemExit((error.stderr or '').strip() or str(error)) from error
