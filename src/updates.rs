//! Self-update from GitHub releases, through fastframe-update.
//!
//! The previous release's helper installs the first release built on the
//! crate, so what it relies on stays the same: `--version` prints
//! `<command> <version>`, the new app accepts `--update-receipt` and
//! `--update-error` (stripped by [`fastframe_update::intercept`] before the
//! argument parser), and the handoff and receipt files keep their format.

pub use fastframe_update::{
    CHECK_INTERVAL, DownloadState, Installation, Kind, Prepared, Release, Source, Unsupported,
    Updater,
};
use fastframe_update::{MacConfig, ReqwestTransport, UpdateConfig};

/// Non-notarized personal builds use an explicit GitHub download.
pub const MANUAL_DOWNLOADS: bool = cfg!(target_os = "macos");

/// A release may never send this personal build back to upstream binaries.
pub fn download_page(url: &str) -> &str {
    if url.starts_with("https://github.com/Tarx2000/spotifast/releases/tag/") {
        url
    } else {
        crate::spotify_compat::RELEASES_URL
    }
}

pub const CONFIG: UpdateConfig = UpdateConfig {
    macos: MacConfig {
        bundle_ids: &["com.spotify.client"],
        executable_names: &["Spotify"],
        legacy_bundle_names: &[],
    },
    // Releases publish an Ed25519 signature for checksums.txt. Require it
    // before downloading an update, using the release workflow's public key.
    publisher_key: Some(include_str!("../fork/update-public-key.hex")),
    // Releases build their AppImages before publishing, so the signed
    // checksums.txt lists them (#737): an AppImage replaces itself with the
    // next one.
    mac_target: fastframe_update::MacTarget::Arm64Only,
    appimage: true,
    ..UpdateConfig::new(
        crate::spotify_compat::UPDATE_REPOSITORY,
        "Spotify",
        "spotifast",
        env!("CARGO_PKG_VERSION"),
    )
};

/// An updater on Spotifast's HTTP client, through the configured proxy.
pub fn updater(proxy: &crate::settings::ProxyConfig) -> anyhow::Result<Updater> {
    let builder = crate::http::blocking_builder(proxy).map_err(anyhow::Error::msg)?;
    Ok(Updater::new(CONFIG, ReqwestTransport::new(builder)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn update_config_is_valid() {
        CONFIG.validate().unwrap();
        assert_eq!(CONFIG.current_version, env!("CARGO_PKG_VERSION"));
    }

    #[test]
    fn download_links_cannot_point_to_unmodified_upstream() {
        assert_eq!(
            download_page("https://github.com/crmne/spotifast/releases/tag/v99"),
            crate::spotify_compat::RELEASES_URL
        );
        assert_eq!(
            download_page("https://github.com/Tarx2000/spotifast/releases/tag/v0.14.1001"),
            "https://github.com/Tarx2000/spotifast/releases/tag/v0.14.1001"
        );
    }

    #[test]
    fn updates_require_the_release_signing_key() {
        assert!(
            CONFIG.publisher_key.is_some(),
            "updates must require a publisher signature"
        );
        CONFIG.validate().unwrap();
    }

    /// An AppImage may replace itself only because the release workflow
    /// builds the AppImages into the signed checksums.txt;
    /// packaging/test-release-names.py checks that side.
    #[test]
    fn appimages_update_themselves() {
        const { assert!(CONFIG.appimage) };
    }
}
