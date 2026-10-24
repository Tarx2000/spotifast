//! Isolated Apple Events fixture. Never opens a profile or starts playback.
#[cfg(target_os = "macos")]
fn main() {
    use objc2_app_kit::{NSApplication, NSApplicationActivationPolicy};
    use objc2_foundation::MainThreadMarker;
    use spotifast::spotify_compat::{Snapshot, install, update};
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    let app = NSApplication::sharedApplication(MainThreadMarker::new().unwrap());
    app.setActivationPolicy(NSApplicationActivationPolicy::Accessory);
    let queue = Arc::new(Mutex::new(Vec::new()));
    install(queue.clone(), spotifast::backend::Waker::default());
    update(Snapshot {
        uri: "spotify:track:fixture".into(),
        title: "Fixture title".into(),
        artist: "Fixture artist".into(),
        album: "Fixture album".into(),
        duration_ms: 245_000,
        position_ms: 12_345,
        volume: 37,
        ..Snapshot::default()
    });
    std::thread::spawn(move || {
        for _ in 0..600 {
            for command in std::mem::take(&mut *queue.lock().unwrap()) {
                println!("{command:?}");
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        std::process::exit(0);
    });
    app.run();
}

#[cfg(not(target_os = "macos"))]
fn main() {}
