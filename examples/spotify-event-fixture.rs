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
    if std::env::args().nth(1).as_deref() == Some("--self-test") {
        use objc2::AnyThread;
        use objc2_foundation::{NSAppleScript, NSString};

        let path = std::env::args().nth(2).expect("AppleScript source path");
        let source = NSString::from_str(&std::fs::read_to_string(path).unwrap());
        let script = NSAppleScript::initWithSource(NSAppleScript::alloc(), &source).unwrap();
        let mut error = None;
        // SAFETY: the bindings infer the documented NSString/AnyObject dictionary.
        // Both script creation and execution stay on the main thread. All events
        // target this fixture, so CI never prompts to control another app.
        let answer = unsafe { script.executeAndReturnError(Some(&mut error)) };
        assert!(error.is_none(), "AppleScript execution failed: {error:?}");
        assert!(
            answer.booleanValue() != 0,
            "AppleScript metadata checks failed"
        );
        println!("AppleScript result: true");
        for command in std::mem::take(&mut *queue.lock().unwrap()) {
            println!("{command:?}");
        }
        return;
    }
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
