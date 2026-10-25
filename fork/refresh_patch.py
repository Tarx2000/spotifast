#!/usr/bin/env python3
"""Record only the personal source changes, independently of upstream releases."""
from pathlib import Path
import json
import re
import subprocess

root = Path(__file__).resolve().parent.parent
config = json.loads((root/'fork/config.json').read_text())
paths = [
    'examples/spotify-event-fixture.rs', 'Cargo.toml', 'src/lib.rs', 'src/spotify_compat.rs', 'src/spotify_compat',
    'src/updates.rs', 'src/entrypoint.rs', 'src/app.rs', 'src/backend.rs', 'src/single_instance.rs',
    'src/window.rs', 'src/demo.rs', 'src/i18n.rs', 'src/mac_menu.rs', 'src/sink.rs', 'src/ui/login.rs',
    'src/ui/settings.rs', 'src/ui/update.rs', 'packaging/macos/Info.plist',
    'packaging/macos/autostart.plist', 'packaging/macos/bundle.sh',
    'packaging/macos/icon-1024.png', 'packaging/macos/Spotify.sdef',
    'tests/packaging_macos.rs',
]
subprocess.run(['git', 'add', '--', *paths], cwd=root, check=True)
patch = subprocess.check_output(['git', 'diff', '--binary', '--full-index',
                                config['patch_base'], '--', *paths], cwd=root)
# Versions are derived from each new upstream tag by prepare.py. A hard-coded
# version hunk would reject every legitimate upstream version increment.
parts = re.split(rb'(?=^diff --git )', patch, flags=re.M)
for i, part in enumerate(parts):
    if part.startswith(b'diff --git a/Cargo.toml b/Cargo.toml'):
        hunks = re.split(rb'(?=^@@ )', part, flags=re.M)
        kept = [hunks[0]]
        for hunk in hunks[1:]:
            changes = [line for line in hunk.splitlines() if line[:1] in (b'+', b'-')]
            if changes and all(re.fullmatch(rb'[+-]version = "[^"]+"', line) for line in changes):
                continue
            kept.append(hunk)
        parts[i] = b''.join(kept)
output = root/'fork/patches/spotify.patch'
output.parent.mkdir(exist_ok=True)
output.write_bytes(b''.join(parts))
print(f'Personal patch recorded: {output.stat().st_size} bytes')
