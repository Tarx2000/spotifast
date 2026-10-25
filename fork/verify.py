#!/usr/bin/env python3
"""Fail closed when a rebuild loses the personal integration or profile identity."""
from pathlib import Path
import hashlib
import json
import plistlib
import re
import tomllib


def verify(root: Path):
    config = json.loads((root / 'fork/config.json').read_text())
    assert config['repository'] == 'Tarx2000/spotifast'
    updates = (root / 'src/updates.rs').read_text()
    compat = (root / 'src/spotify_compat.rs').read_text()
    native = (root / 'src/spotify_compat/native.rs').read_text()
    app = (root / 'src/app.rs').read_text()
    entrypoint = (root / 'src/entrypoint.rs').read_text()
    assert 'crate::spotify_compat::UPDATE_REPOSITORY' in updates
    assert '"Tarx2000/spotifast"' in compat
    assert 'bundle_ids: &["com.spotify.client"]' in updates
    assert 'executable_names: &["Spotify"]' in updates
    assert 'MANUAL_DOWNLOADS: bool = cfg!(target_os = "macos")' in updates
    assert 'fork/update-public-key.hex' in updates
    assert 'spotify_compat::install(guard.commands()' in entrypoint
    assert 'spotify_compat::update(self.spotify_snapshot())' in app
    assert entrypoint.index('spotify_compat::cli::run_if_cli') < entrypoint.index('fastframe_update::intercept')
    assert 'ControlCommand::SetSaved' in app and 'Action::SetSavedMany' in app
    cli = (root/'src/spotify_compat/cli.rs').read_text()
    assert 'single_instance::send' in cli and 'save-set' in cli
    for forbidden in ['reqwest', 'Command::new', 'NSApplication', 'credentials::']:
        assert forbidden not in cli, f'Unexpected CLI work: {forbidden}'
    assert "(contents/'MacOS/spotify_cli').symlink_to('Spotify')" in (root/'fork/package.py').read_text()
    assert 'Track ID' in native and 'PlaybackStateChanged' in native
    assert 'now.uri' in app and 'pTrk' in compat
    for forbidden in ['std::process', 'Command::new', 'Timer::', 'reqwest', 'URLSession']:
        assert forbidden not in native, f'Unexpected runtime work: {forbidden}'
    assert 'App::new("spotifast", "me", "paolino", "spotifast")' in (root/'src/paths.rs').read_text()
    assert 'const SERVICE: &str = "rocks.spotifast.Spotifast"' in (root/'src/credentials.rs').read_text()
    assert 'eframe::storage_dir("spotifast")' in entrypoint
    info = plistlib.loads((root/'packaging/macos/Info.plist').read_bytes())
    assert info['CFBundleName'] == info['CFBundleDisplayName'] == 'Spotify'
    assert info['OSAScriptingDefinition'] == 'Spotify.sdef'
    assert info['NSAppleScriptEnabled'] is True
    assert 'identifier=com.spotify.client' in (root/'packaging/macos/bundle.sh').read_text()
    assert 'pTrk' in (root/'packaging/macos/Spotify.sdef').read_text()
    public = (root/'fork/update-public-key.hex').read_text().strip()
    assert re.fullmatch('[0-9a-f]{64}', public)
    if (root/'fork/upstream.json').exists():
        provenance = json.loads((root/'fork/upstream.json').read_text())
        patch = root/'fork/patches/spotify.patch'
        assert provenance['patch_sha256'] == hashlib.sha256(patch.read_bytes()).hexdigest()
        assert provenance['personal_version'] == tomllib.loads((root/'Cargo.toml').read_text())['package']['version']
    print('Personal integration, update channel, and profile guards passed.')


if __name__ == '__main__':
    verify(Path(__file__).resolve().parent.parent)
