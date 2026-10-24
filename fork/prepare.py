#!/usr/bin/env python3
"""Rebuild a clean stable upstream tree with the complete personal patch.

No three-way fallback, forced hunks, skipped files or unpatched fallback.
The installed app is never involved. A failed patch leaves it untouched.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import urllib.request

from verify import verify


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def version_for(tag, revision):
    match = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', tag)
    if not match or not 1 <= revision <= 999:
        raise ValueError('A stable upstream tag and personal revision 1..999 are required.')
    major, minor, patch = map(int, match.groups())
    return f'{major}.{minor}.{patch * 1000 + revision}'


def stamp_version(candidate, version):
    cargo = candidate/'Cargo.toml'
    old = tomllib.loads(cargo.read_text())['package']['version']
    cargo.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', cargo.read_text(), count=1))
    lock = candidate/'Cargo.lock'
    original = f'name = "spotifast"\nversion = "{old}"'
    assert lock.read_text().count(original) == 1
    lock.write_text(lock.read_text().replace(original, f'name = "spotifast"\nversion = "{version}"'))


def latest_tag(config):
    request = urllib.request.Request(f'https://api.github.com/repos/{config["upstream"]}/releases/latest',
                                     headers={'User-Agent': 'spotifast-personal-builder'})
    if os.environ.get('GH_TOKEN'):
        request.add_header('Authorization', 'Bearer ' + os.environ['GH_TOKEN'])
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    if release['draft'] or release['prerelease']:
        raise ValueError('Only published stable upstream releases are accepted.')
    return release['tag_name']


def sync_source(candidate, root):
    # Only tracked source is removed. Build caches and unrelated local files
    # are never swept. CI invokes this only on its clean, disposable checkout.
    tracked = run('git', 'ls-files', '-z', cwd=root).split('\0')
    wanted = {str(p.relative_to(candidate)) for p in candidate.rglob('*')
              if p.is_file() and '.git' not in p.relative_to(candidate).parts}
    for relative in tracked:
        if relative and relative not in wanted:
            (root/relative).unlink(missing_ok=True)
    for relative in wanted:
        target = root/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate/relative, target)


def prepare(root, tag, output):
    config = json.loads((root/'fork/config.json').read_text())
    tag = tag or latest_tag(config)
    version = version_for(tag, config['revision'])
    ref = f'refs/tags/personal-upstream/{tag}'
    subprocess.run(['git', 'fetch', '--no-tags', f'https://github.com/{config["upstream"]}.git',
                    f'refs/tags/{tag}:{ref}'], cwd=root, check=True)
    commit = run('git', 'rev-parse', f'{ref}^{{commit}}', cwd=root)
    if output.exists():
        raise ValueError(f'Candidate directory already exists: {output}')
    output.mkdir(parents=True)
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['git', 'archive', commit], cwd=root, stdout=archive, check=True)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as tar:
            members = tar.getmembers()
            if any(m.issym() or m.islnk() for m in members):
                raise ValueError('Unexpected upstream links require review.')
            tar.extractall(output, members=members, filter='data')
    subprocess.run(['git', 'init', '-q', str(output)], check=True)
    patch = root/'fork/patches/spotify.patch'
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=output, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=output, check=True)
    stamp_version(output, version)
    # The personal policy and workflow always come from our current branch.
    # Upstream cannot replace them through an automatic synchronization.
    shutil.copytree(root/'fork', output/'fork')
    workflows = output/'.github/workflows'
    shutil.rmtree(workflows)
    workflows.mkdir()
    shutil.copy2(root/'.github/workflows/personal.yml', workflows/'personal.yml')
    provenance = {'upstream_tag': tag, 'upstream_commit': commit, 'personal_version': version,
                  'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest()}
    (output/'fork/upstream.json').write_text(json.dumps(provenance, indent=2)+'\n')
    original_readme = (output/'README.md').read_text()
    (output/'README.md').write_text(
        '> Personal macOS fork with integrated Spotify compatibility. '
        'Not an official Spotify application. [Update policy and build instructions](fork/README.md).\n\n'
        + original_readme)
    with (output/'.gitignore').open('a') as ignored:
        ignored.write('\n# Personal build tooling\n__pycache__/\n*.pyc\n.DS_Store\n')
    verify(output)
    return provenance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.write and run('git', 'status', '--porcelain', cwd=root):
        raise ValueError('Automatic synchronization requires a clean checkout.')
    config = json.loads((root/'fork/config.json').read_text())
    tag = args.tag or latest_tag(config)
    version = version_for(tag, config['revision'])
    if args.write:
        existing = subprocess.run(['gh', 'api', f'repos/{config["repository"]}/releases/tags/v{version}'],
                                  cwd=root, capture_output=True, text=True, timeout=40)
        if existing.returncode == 0 and not json.loads(existing.stdout)['draft']:
            print(f'Personal version {version} is already published. Nothing to publish.')
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'], 'a') as f: f.write('changed=false\n')
            return
        if existing.returncode and 'HTTP 404' not in existing.stderr:
            raise RuntimeError('Could not check the personal release. No update will be built.')
        current = tomllib.loads((root/'Cargo.toml').read_text())['package']['version']
        if tuple(map(int, version.split('.'))) < tuple(map(int, current.split('.'))):
            raise ValueError('Automatic downgrades are refused.')
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix='spotifast-personal-'))/'source'
    provenance = prepare(root, tag, output)
    if args.write:
        sync_source(output, root)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f'changed=true\nversion={version}\n')
    print(json.dumps(provenance, indent=2))


if __name__ == '__main__':
    main()
