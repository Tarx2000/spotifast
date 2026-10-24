#!/usr/bin/env python3
"""Exercise the real Apple Events handlers using only invented fixture state."""
from pathlib import Path
import argparse
import tempfile
import json
import plistlib
import shutil
import subprocess
import time

source = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--binary', type=Path, required=True)
args = parser.parse_args()
(source/'target').mkdir(exist_ok=True)
fixture = tempfile.TemporaryDirectory(prefix='native-events-', dir=source/'target')
app = Path(fixture.name)/'Spotify.app'
contents = app/'Contents'
(contents/'MacOS').mkdir(parents=True, exist_ok=True)
(contents/'Resources').mkdir(exist_ok=True)
shutil.copy2(args.binary.resolve(), contents/'MacOS/Fixture')
shutil.copy2(source/'packaging/macos/Spotify.sdef', contents/'Resources/Spotify.sdef')
(contents/'Info.plist').write_bytes(plistlib.dumps({
    'CFBundleIdentifier': 'com.spotify.client', 'CFBundleName': 'Spotify',
    'CFBundleDisplayName': 'Spotify', 'CFBundleExecutable': 'Fixture',
    'CFBundlePackageType': 'APPL', 'NSAppleScriptEnabled': True,
    'OSAScriptingDefinition': 'Spotify.sdef', 'LSUIElement': True,
}))
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True)
script = f'''tell application "{app}"
    set valid to (name of current track is "Fixture title") and (artist of current track is "Fixture artist") and (id of current track is "spotify:track:fixture") and (duration of current track is 245000) and (player position is 12.345) and (player state is paused) and (sound volume is 37)
    set sound volume to 37
    set player position to 45.5
    set shuffling to false
    set repeating to false
    play
    pause
    playpause
    next track
    previous track
    return valid
end tell'''
process = subprocess.Popen([str(contents/'MacOS/Fixture')], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    time.sleep(2)
    answer = subprocess.run(['osascript','-e',script],capture_output=True,text=True,timeout=10)
    print('AppleScript exit:',answer.returncode,'result:',answer.stdout.strip(),'error:',answer.stderr.strip(),flush=True)
    time.sleep(0.2)
finally:
    if process.poll() is None: process.terminate()
    stdout, stderr = process.communicate(timeout=5)
    print('Fixture commands:',stdout.strip(),'diagnostics:',stderr[:1500],flush=True)
    subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', '-u', str(app)], check=False, capture_output=True)
    fixture.cleanup()

assert answer.returncode == 0 and answer.stdout.strip() == 'true'
for command in ['SetVolume(37)', 'SeekTo(45500)', 'SetShuffle(false)', 'SetRepeat(Off)',
                'Play', 'Pause', 'PlayPause', 'Next', 'Previous']:
    assert command in stdout, command
print('Seven live-property checks and nine in-process command translations passed.')
