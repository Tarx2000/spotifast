//! The small subset of Spotify's bundled CLI that Canopy uses for its heart.
//!
//! `spotify_cli` is a relative link to the player executable. This entry point
//! exits before starting a window, backend, account, or second player. It only
//! talks to the existing per-user control channel.

use std::ffi::OsString;
use std::io::Write;
use std::path::Path;
use std::time::{Duration, Instant};

use serde_json::{Value, json};

use crate::single_instance::{self, Reply};

#[derive(Debug, PartialEq)]
enum Command {
    NowPlaying,
    Contains(String),
    Save { uri: String, saved: bool },
}

fn parse(args: &[String]) -> Result<Command, &'static str> {
    if args.len() > 12 || args.iter().any(|s| s.len() > 256) {
        return Err("Too many or oversized CLI arguments.");
    }
    let mut positional = Vec::new();
    let mut args = args.iter();
    while let Some(argument) = args.next() {
        if argument == "--format" {
            if args.next().map(String::as_str) != Some("json") {
                return Err("The personal Spotify CLI supports JSON output.");
            }
        } else if argument == "--format=json" {
            continue;
        } else {
            positional.push(argument.as_str());
        }
    }
    match positional.as_slice() {
        ["now-playing"] => Ok(Command::NowPlaying),
        ["library", verb, uri] => {
            let uri = single_instance::spotify_track_uri(uri)
                .ok_or("A canonical Spotify track URI is required.")?;
            match *verb {
                "contains" => Ok(Command::Contains(uri)),
                "add" => Ok(Command::Save { uri, saved: true }),
                "remove" => Ok(Command::Save { uri, saved: false }),
                _ => Err("Unsupported library command."),
            }
        }
        _ => {
            Err("Supported: now-playing; library contains/add/remove <track URI> [--format json].")
        }
    }
}

#[derive(Debug)]
struct Track {
    uri: String,
    title: String,
    artist: String,
    album: String,
    position_ms: u32,
    duration_ms: u32,
    playing: bool,
    saved: Option<bool>,
}

impl Track {
    fn from_snapshot(snapshot: &str) -> Result<Option<Self>, &'static str> {
        if snapshot == single_instance::NOTHING_PLAYING {
            return Ok(None);
        }
        let fields: Vec<_> = snapshot.split('\t').collect();
        if fields.len() < 13 {
            return Err("Restart the updated Spotify app before using its CLI.");
        }
        Ok(Some(Self {
            uri: single_instance::spotify_track_uri(fields[12])
                .ok_or("The current item is not a Spotify track.")?,
            title: fields[1].to_owned(),
            artist: fields[2].to_owned(),
            album: fields[3].to_owned(),
            position_ms: fields[4].parse().map_err(|_| "Invalid player position.")?,
            duration_ms: fields[5].parse().map_err(|_| "Invalid track duration.")?,
            playing: fields[0] == "playing",
            saved: match fields[10] {
                "yes" => Some(true),
                "no" => Some(false),
                _ => None,
            },
        }))
    }

    fn contains(&self, uri: &str) -> Result<bool, &'static str> {
        if self.uri != uri {
            return Err("This compatibility CLI only exposes the current track.");
        }
        self.saved
            .ok_or("The player's saved state is still loading.")
    }

    fn now_playing(&self) -> Value {
        json!({
            "currently_playing": {
                "uri": self.uri,
                "name": self.title,
                "description": format!("{} - {}", self.title, self.artist),
                "artists": [{"name": self.artist}],
                "album": {"name": self.album},
                "duration_ms": self.duration_ms,
                "is_saved": self.saved,
            },
            "is_playing": self.playing,
            "progress_ms": self.position_ms,
        })
    }
}

fn current() -> anyhow::Result<Option<Track>> {
    let Reply::NowPlaying(snapshot) = single_instance::send("nowplaying")? else {
        anyhow::bail!("The player did not return a track snapshot.");
    };
    Track::from_snapshot(&snapshot).map_err(anyhow::Error::msg)
}

fn execute(command: Command) -> anyhow::Result<Value> {
    if command == Command::NowPlaying {
        return Ok(current()?.map_or_else(
            || json!({"currently_playing": null, "is_playing": false}),
            |track| track.now_playing(),
        ));
    }
    let track = current()?.ok_or_else(|| anyhow::anyhow!("No track is playing."))?;
    match command {
        Command::Contains(uri) => {
            let saved = track.contains(&uri).map_err(anyhow::Error::msg)?;
            Ok(json!({"contains": {uri: saved}}))
        }
        Command::Save { uri, saved } => {
            if track.uri != uri {
                anyhow::bail!("The current track changed. No library change was sent.");
            }
            if track.saved == Some(saved) {
                return Ok(json!({"success": true}));
            }
            let state = if saved { "on" } else { "off" };
            if !matches!(
                single_instance::send(&format!("save-set {state} {uri}"))?,
                Reply::Ok
            ) {
                anyhow::bail!("The player did not accept the library command.");
            }
            // A short command waits for the player's optimistic state. There is
            // no polling service; this process exits after the explicit click.
            let deadline = Instant::now() + Duration::from_secs(2);
            while Instant::now() < deadline {
                if let Some(track) = current()?
                    && track.uri == uri
                    && track.saved == Some(saved)
                {
                    return Ok(json!({"success": true}));
                }
                std::thread::sleep(Duration::from_millis(20));
            }
            anyhow::bail!("The player has not reflected the library command yet.");
        }
        Command::NowPlaying => unreachable!(),
    }
}

/// `None` leaves an ordinary player or Spotifast control launch unchanged.
pub fn run_if_cli(arguments: impl IntoIterator<Item = OsString>) -> Option<i32> {
    let mut arguments = arguments.into_iter();
    let program = arguments.next()?;
    if Path::new(&program).file_name()? != "spotify_cli" {
        return None;
    }
    let result = arguments
        .map(|arg| {
            arg.into_string()
                .map_err(|_| anyhow::anyhow!("Arguments must be UTF-8."))
        })
        .collect::<anyhow::Result<Vec<_>>>()
        .and_then(|args| parse(&args).map_err(anyhow::Error::msg))
        .and_then(execute);
    Some(match result {
        Ok(value) => i32::from(writeln!(std::io::stdout().lock(), "{value}").is_err()),
        Err(error) => {
            let _ = writeln!(
                std::io::stderr().lock(),
                "Spotify compatibility CLI: {error}"
            );
            1
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    #[test]
    fn canopy_commands_accept_json_flags_and_reject_unrelated_or_injected_requests() {
        assert_eq!(
            parse(&args(&["--format", "json", "now-playing"])),
            Ok(Command::NowPlaying)
        );
        assert_eq!(
            parse(&args(&[
                "library",
                "contains",
                "spotify:track:abc",
                "--format=json"
            ])),
            Ok(Command::Contains("spotify:track:abc".into()))
        );
        for verb in ["add", "remove"] {
            assert_eq!(
                parse(&args(&["library", verb, "spotify:track:abc"])),
                Ok(Command::Save {
                    uri: "spotify:track:abc".into(),
                    saved: verb == "add"
                })
            );
        }
        for request in [
            vec!["library", "add", "spotify:track:abc\nnext"],
            vec!["library", "remove", "spotify:playlist:abc"],
            vec!["library", "batch"],
            vec!["now-playing", "--format", "xml"],
        ] {
            assert!(parse(&args(&request)).is_err());
        }
        assert_eq!(run_if_cli([OsString::from("Spotify")]), None);
    }

    #[test]
    fn unknown_or_stale_likes_are_not_reported_as_false() {
        let snapshot = "paused\tTitle\tArtist\tAlbum\t12000\t200000\t35\toff\toff\t\tunknown\tSpotify\tspotify:track:abc";
        let track = Track::from_snapshot(snapshot).unwrap().unwrap();
        assert!(track.contains("spotify:track:abc").is_err());
        assert!(track.contains("spotify:track:other").is_err());
        assert_eq!(
            track.now_playing()["currently_playing"]["uri"],
            "spotify:track:abc"
        );
        assert!(Track::from_snapshot("playing\told snapshot").is_err());
        assert!(Track::from_snapshot("stopped").unwrap().is_none());
        let liked = Track::from_snapshot(&snapshot.replace("unknown", "yes"))
            .unwrap()
            .unwrap();
        assert_eq!(liked.contains("spotify:track:abc"), Ok(true));
    }
}
