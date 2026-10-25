//! Local Spotify Apple Events, handled inside the player process.
//!
//! The original profile, credential service and instance slot are unchanged.
//! No timers, child processes, network requests or extra artwork cache.

use crate::single_instance::ControlCommand;

#[cfg(any(target_os = "macos", test))]
pub mod cli;

pub const DISPLAY_NAME: &str = if cfg!(target_os = "macos") {
    "Spotify"
} else {
    "Spotifast"
};
pub const UPDATE_REPOSITORY: &str = "Tarx2000/spotifast";
pub const SOURCE_URL: &str = "https://github.com/Tarx2000/spotifast";
pub const RELEASES_URL: &str = "https://github.com/Tarx2000/spotifast/releases";

pub const fn code(bytes: &[u8; 4]) -> u32 {
    u32::from_be_bytes(*bytes)
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Snapshot {
    pub uri: String,
    pub title: String,
    pub artist: String,
    pub album: String,
    pub artwork_url: String,
    pub duration_ms: u32,
    pub position_ms: u32,
    pub volume: u8,
    pub playing: bool,
    pub shuffle: bool,
    pub repeating: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Text(String),
    Integer(i32),
    Real(f64),
    Boolean(bool),
    Enum(u32),
    Track,
    Missing,
}

impl Snapshot {
    pub fn read(&self, property: u32, track: bool) -> Option<Value> {
        use Value::*;
        if track {
            if self.uri.is_empty() {
                return Some(Missing);
            }
            return Some(match property {
                p if p == code(b"pnam") => Text(self.title.clone()),
                p if p == code(b"pArt") => Text(self.artist.clone()),
                p if p == code(b"pAlb") => Text(self.album.clone()),
                p if p == code(b"pDur") => Integer(self.duration_ms.min(i32::MAX as u32) as i32),
                p if p == code(b"ID  ") => Text(self.uri.clone()),
                p if p == code(b"sUrl") => Text(self.uri.clone()),
                p if p == code(b"aUrl") => Text(self.artwork_url.clone()),
                _ => return None,
            });
        }
        Some(match property {
            p if p == code(b"pnam") => Text(DISPLAY_NAME.into()),
            p if p == code(b"vers") => Text(env!("CARGO_PKG_VERSION").into()),
            p if p == code(b"pTrk") => {
                if self.uri.is_empty() {
                    Missing
                } else {
                    Track
                }
            }
            p if p == code(b"pVol") => Integer(i32::from(self.volume)),
            p if p == code(b"pPos") => Real(f64::from(self.position_ms) / 1000.0),
            p if p == code(b"pPlS") => Enum(if self.uri.is_empty() {
                code(b"kPSS")
            } else if self.playing {
                code(b"kPSP")
            } else {
                code(b"kPSp")
            }),
            p if p == code(b"pShf") => Boolean(self.shuffle),
            p if p == code(b"pRpt") => Boolean(self.repeating),
            p if p == code(b"pShE") || p == code(b"pRpE") => Boolean(true),
            _ => return None,
        })
    }
}

pub fn numeric_command(property: u32, value: f64) -> Option<ControlCommand> {
    if !value.is_finite() {
        return None;
    }
    if property == code(b"pVol") && (0.0..=100.0).contains(&value) {
        Some(ControlCommand::SetVolume(value.round() as u8))
    } else if property == code(b"pPos") && (0.0..=f64::from(u32::MAX) / 1000.0).contains(&value) {
        Some(ControlCommand::SeekTo((value * 1000.0).round() as u32))
    } else {
        None
    }
}

#[cfg(target_os = "macos")]
mod native;
#[cfg(target_os = "macos")]
pub use native::{install, update};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spotify_units_and_track_identity_come_from_the_live_player() {
        let s = Snapshot {
            uri: "spotify:track:test".into(),
            duration_ms: 120_123,
            position_ms: 12_345,
            volume: 37,
            playing: true,
            ..Snapshot::default()
        };
        assert_eq!(s.read(code(b"pPos"), false), Some(Value::Real(12.345)));
        assert_eq!(s.read(code(b"pDur"), true), Some(Value::Integer(120_123)));
        assert_eq!(
            s.read(code(b"ID  "), true),
            Some(Value::Text(s.uri.clone()))
        );
        assert_eq!(
            s.read(code(b"pPlS"), false),
            Some(Value::Enum(code(b"kPSP")))
        );
        assert_eq!(
            numeric_command(code(b"pPos"), 12.345),
            Some(ControlCommand::SeekTo(12_345))
        );
    }

    #[test]
    fn invalid_setters_and_missing_tracks_do_not_invent_state() {
        for value in [f64::NAN, f64::INFINITY, -1.0, 101.0] {
            assert!(numeric_command(code(b"pVol"), value).is_none());
        }
        assert!(numeric_command(code(b"pPos"), f64::MAX).is_none());
        assert_eq!(
            Snapshot::default().read(code(b"pTrk"), false),
            Some(Value::Missing)
        );
        assert_eq!(
            Snapshot::default().read(code(b"pPlS"), false),
            Some(Value::Enum(code(b"kPSS")))
        );
        assert_eq!(Snapshot::default().read(code(b"nope"), false), None);
    }

    #[test]
    fn updates_are_always_from_the_personal_channel() {
        assert_eq!(crate::updates::CONFIG.repository, UPDATE_REPOSITORY);
        assert_ne!(UPDATE_REPOSITORY, "crmne/spotifast");
    }
}
