#!/usr/bin/env python3
"""Create the personal, ad-hoc-signed macOS app and downloadable packages.

No Gatekeeper changes, quarantine removal, Developer ID, or notarization.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile
import tomllib


def package(binary, output, dmg):
    root = Path(__file__).resolve().parent.parent
    version = tomllib.loads((root/'Cargo.toml').read_text())['package']['version']
    output.mkdir(parents=True, exist_ok=True)
    app = output/'Spotify.app'
    if app.exists(): raise ValueError(f'Refusing to replace an existing app: {app}')
    contents = app/'Contents'
    resources = contents/'Resources'
    (contents/'MacOS').mkdir(parents=True)
    resources.mkdir()
    shutil.copy2(binary, contents/'MacOS/Spotify')
    (contents/'MacOS/Spotify').chmod(0o755)
    template = (root/'packaging/macos/Info.plist').read_text()
    for key, value in {'__VERSION__': version, '__BUILD__': version,
                       '__EXECUTABLE__': 'Spotify', '__IDENTIFIER__': 'com.spotify.client'}.items():
        template = template.replace(key, value)
    (contents/'Info.plist').write_text(template)
    shutil.copy2(root/'packaging/macos/Spotify.sdef', resources/'Spotify.sdef')
    agents = contents/'Library/LaunchAgents'
    agents.mkdir(parents=True)
    shutil.copy2(root/'packaging/macos/autostart.plist', agents/'com.spotify.client.autostart.plist')
    chunks = []
    with tempfile.TemporaryDirectory() as directory:
        for typ, size in [('icp4', 16), ('icp5', 32), ('icp6', 64), ('ic07', 128),
                          ('ic08', 256), ('ic09', 512), ('ic10', 1024)]:
            png = Path(directory)/f'{size}.png'
            subprocess.run(['sips', '-z', str(size), str(size), str(root/'packaging/macos/icon-1024.png'),
                            '--out', str(png)], check=True, stdout=subprocess.DEVNULL)
            data = png.read_bytes()
            chunks.append(typ.encode()+struct.pack('>I', len(data)+8)+data)
    data = b''.join(chunks)
    (resources/'spotifast.icns').write_bytes(b'icns'+struct.pack('>I', len(data)+8)+data)
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True)
    info = plistlib.loads((contents/'Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == 'com.spotify.client'
    assert info['CFBundleName'] == 'Spotify'
    archive = output/f'spotifast-v{version}-macos-arm64.zip'
    subprocess.run(['ditto', '-c', '-k', '--keepParent', str(app), str(archive)], check=True)
    packages = [archive]
    if dmg:
        disk = output/f'spotifast-v{version}-macos-arm64.dmg'
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory)
            subprocess.run(['ditto', str(app), str(staging/'Spotify.app')], check=True)
            (staging/'Applications').symlink_to('/Applications')
            subprocess.run(['hdiutil', 'create', '-volname', 'Spotify Personal', '-srcfolder', str(staging),
                            '-format', 'UDZO', str(disk)], check=True)
        packages.append(disk)
    provenance = root/'fork/upstream.json'
    if provenance.exists():
        shutil.copy2(provenance, output/'build-source.json')
        packages.append(output/'build-source.json')
    manifest = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in packages)
    (output/'checksums.txt').write_text(manifest)
    print(json.dumps({'version': version, 'app': str(app), 'packages': [p.name for p in packages]}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dmg', action='store_true')
    args = parser.parse_args()
    package(args.binary.resolve(), args.output.resolve(), args.dmg)
