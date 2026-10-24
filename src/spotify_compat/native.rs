use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use objc2::rc::Retained;
use objc2::{MainThreadOnly, define_class, msg_send, sel};
use objc2_foundation::{
    MainThreadMarker, NSAppleEventDescriptor as Descriptor, NSAppleEventManager, NSDictionary,
    NSDistributedNotificationCenter, NSObject, NSString,
};

use super::{Snapshot, Value, code, numeric_command};
use crate::backend::Waker;
use crate::player::RepeatMode;
use crate::single_instance::ControlCommand;

type Sink = (Arc<Mutex<Vec<ControlCommand>>>, Waker);
static SINK: Mutex<Option<Sink>> = Mutex::new(None);
static SNAPSHOT: Mutex<Option<Snapshot>> = Mutex::new(None);

fn descriptor_type(value: &Descriptor) -> u32 {
    unsafe { msg_send![value, descriptorType] }
}

fn param(event: &Descriptor, key: u32) -> Option<Retained<Descriptor>> {
    unsafe { msg_send![event, paramDescriptorForKeyword: key] }
}
fn field(record: &Descriptor, key: u32) -> Option<Retained<Descriptor>> {
    unsafe { msg_send![record, descriptorForKeyword: key] }
}
fn set_field(record: &Descriptor, key: u32, value: &Descriptor) {
    unsafe {
        let _: () = msg_send![record, setDescriptor: value, forKeyword: key];
    }
}
fn reply_value(reply: &Descriptor, key: u32, value: &Descriptor) {
    unsafe {
        let _: () = msg_send![reply, setParamDescriptor: value, forKeyword: key];
    }
}
fn error(reply: &Descriptor, number: i32) {
    reply_value(
        reply,
        code(b"errn"),
        &Descriptor::descriptorWithInt32(number),
    );
}
fn text(value: &str) -> Retained<Descriptor> {
    Descriptor::descriptorWithString(&NSString::from_str(value))
}

// Only the application's own property and current-track specifiers are
// accepted. Never evaluate arbitrary object specifiers or incoming code.
fn property(specifier: &Descriptor, depth: u8) -> Option<(u32, bool)> {
    if depth > 3 || descriptor_type(specifier) != code(b"obj ") {
        return None;
    }
    if field(specifier, code(b"want"))?.typeCodeValue() != code(b"prop") {
        return None;
    }
    if field(specifier, code(b"form"))?.enumCodeValue() != code(b"prop") {
        return None;
    }
    let selected = field(specifier, code(b"seld"))?.typeCodeValue();
    let container = field(specifier, code(b"from"))?;
    if descriptor_type(&container) == code(b"null") {
        return Some((selected, false));
    }
    let (parent, track) = property(&container, depth + 1)?;
    (parent == code(b"pTrk") && !track).then_some((selected, true))
}

fn descriptor(value: Value, state: &Snapshot) -> Retained<Descriptor> {
    match value {
        Value::Text(value) => text(&value),
        Value::Integer(value) => Descriptor::descriptorWithInt32(value),
        Value::Real(value) => Descriptor::descriptorWithDouble(value),
        Value::Boolean(value) => Descriptor::descriptorWithBoolean(u8::from(value)),
        Value::Enum(value) => Descriptor::descriptorWithEnumCode(value),
        Value::Missing => Descriptor::nullDescriptor(),
        Value::Track => {
            let record = Descriptor::recordDescriptor();
            for key in [
                code(b"pnam"),
                code(b"pArt"),
                code(b"pAlb"),
                code(b"pDur"),
                code(b"ID  "),
                code(b"aUrl"),
                code(b"sUrl"),
            ] {
                if let Some(value) = state.read(key, true) {
                    set_field(&record, key, &descriptor(value, state));
                }
            }
            record
        }
    }
}

fn enqueue(command: ControlCommand, reply: &Descriptor) {
    let guard = SINK.lock().unwrap_or_else(|p| p.into_inner());
    let Some((queue, waker)) = guard.as_ref() else {
        error(reply, -600);
        return;
    };
    queue
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .push(command);
    waker.wake();
}

fn get(event: &Descriptor, reply: &Descriptor) {
    let Some((key, track)) = param(event, code(b"----")).and_then(|s| property(&s, 0)) else {
        error(reply, -1728);
        return;
    };
    let guard = SNAPSHOT.lock().unwrap_or_else(|p| p.into_inner());
    let state = guard.clone().unwrap_or_default();
    drop(guard);
    match state.read(key, track) {
        Some(value) => reply_value(reply, code(b"----"), &descriptor(value, &state)),
        None => error(reply, -1728),
    }
}

fn set(event: &Descriptor, reply: &Descriptor) {
    let Some((key, false)) = param(event, code(b"----")).and_then(|s| property(&s, 0)) else {
        error(reply, -1728);
        return;
    };
    let Some(data) = param(event, code(b"data")) else {
        error(reply, -1701);
        return;
    };
    let kind = descriptor_type(&data);
    let boolean = key == code(b"pShf") || key == code(b"pRpt");
    let accepted = if boolean {
        [code(b"bool"), code(b"true"), code(b"fals")].contains(&kind)
    } else {
        [
            code(b"long"),
            code(b"shor"),
            code(b"comp"),
            code(b"doub"),
            code(b"sing"),
            code(b"magn"),
        ]
        .contains(&kind)
    };
    if !accepted {
        error(reply, -1700);
        return;
    }
    let command = if boolean {
        let value = data.booleanValue() != 0;
        if key == code(b"pShf") {
            Some(ControlCommand::SetShuffle(value))
        } else {
            Some(ControlCommand::SetRepeat(if value {
                RepeatMode::Context
            } else {
                RepeatMode::Off
            }))
        }
    } else {
        numeric_command(key, data.doubleValue())
    };
    match command {
        Some(command) => enqueue(command, reply),
        None => error(reply, -1700),
    }
}

fn command(event: &Descriptor, reply: &Descriptor) {
    let id: u32 = unsafe { msg_send![event, eventID] };
    let command = match id {
        c if c == code(b"PlPs") => ControlCommand::PlayPause,
        c if c == code(b"Play") => ControlCommand::Play,
        c if c == code(b"Paus") => ControlCommand::Pause,
        c if c == code(b"Next") => ControlCommand::Next,
        c if c == code(b"Prev") => ControlCommand::Previous,
        c if c == code(b"PCtx") => {
            if param(event, code(b"ctxt")).is_some() {
                error(reply, -1708);
                return;
            }
            let Some(uri) = param(event, code(b"----"))
                .and_then(|d| d.stringValue())
                .and_then(|s| crate::link::parse(&s.to_string()))
            else {
                error(reply, -1700);
                return;
            };
            ControlCommand::PlayUri(uri)
        }
        _ => {
            error(reply, -1708);
            return;
        }
    };
    enqueue(command, reply);
}

define_class!(
    #[unsafe(super(NSObject))]
    #[thread_kind = MainThreadOnly]
    #[name = "PersonalSpotifyEventHandler"]
    struct Handler;
    impl Handler {
        #[unsafe(method(handleGet:withReplyEvent:))]
        fn handle_get(&self, event: &Descriptor, reply: &Descriptor) { get(event, reply); }
        #[unsafe(method(handleSet:withReplyEvent:))]
        fn handle_set(&self, event: &Descriptor, reply: &Descriptor) { set(event, reply); }
        #[unsafe(method(handleCommand:withReplyEvent:))]
        fn handle_command(&self, event: &Descriptor, reply: &Descriptor) { command(event, reply); }
    }
);

pub fn install(commands: Arc<Mutex<Vec<ControlCommand>>>, waker: Waker) {
    let Some(mtm) = MainThreadMarker::new() else {
        return;
    };
    *SINK.lock().unwrap_or_else(|p| p.into_inner()) = Some((commands, waker));
    static INSTALLED: AtomicBool = AtomicBool::new(false);
    if INSTALLED.swap(true, Ordering::SeqCst) {
        return;
    }
    let handler: Retained<Handler> = unsafe { msg_send![mtm.alloc::<Handler>(), init] };
    let manager = NSAppleEventManager::sharedAppleEventManager();
    for (class, id, selector) in [
        (
            code(b"core"),
            code(b"getd"),
            sel!(handleGet:withReplyEvent:),
        ),
        (
            code(b"core"),
            code(b"setd"),
            sel!(handleSet:withReplyEvent:),
        ),
        (
            code(b"spfy"),
            code(b"PlPs"),
            sel!(handleCommand:withReplyEvent:),
        ),
        (
            code(b"spfy"),
            code(b"Play"),
            sel!(handleCommand:withReplyEvent:),
        ),
        (
            code(b"spfy"),
            code(b"Paus"),
            sel!(handleCommand:withReplyEvent:),
        ),
        (
            code(b"spfy"),
            code(b"Next"),
            sel!(handleCommand:withReplyEvent:),
        ),
        (
            code(b"spfy"),
            code(b"Prev"),
            sel!(handleCommand:withReplyEvent:),
        ),
        (
            code(b"spfy"),
            code(b"PCtx"),
            sel!(handleCommand:withReplyEvent:),
        ),
    ] {
        unsafe {
            let _: () = msg_send![&*manager, setEventHandler: &*handler,
            andSelector: selector, forEventClass: class, andEventID: id];
        }
    }
    std::mem::forget(handler);
}

pub fn update(state: Snapshot) {
    if cfg!(test) || SINK.lock().unwrap_or_else(|p| p.into_inner()).is_none() {
        return;
    }
    let mut guard = SNAPSHOT.lock().unwrap_or_else(|p| p.into_inner());
    let changed = guard.as_ref().is_none_or(|old| {
        old.uri != state.uri
            || old.title != state.title
            || old.artist != state.artist
            || old.album != state.album
            || old.artwork_url != state.artwork_url
            || old.playing != state.playing
            || old.shuffle != state.shuffle
            || old.repeating != state.repeating
            || old.volume != state.volume
    });
    if changed {
        let keys: Vec<_> = ["Player State", "Name", "Artist", "Album", "Track ID"]
            .map(NSString::from_str)
            .into();
        let playback = if state.uri.is_empty() {
            "Stopped"
        } else if state.playing {
            "Playing"
        } else {
            "Paused"
        };
        let values: Vec<_> = [
            playback,
            &state.title,
            &state.artist,
            &state.album,
            &state.uri,
        ]
        .map(NSString::from_str)
        .into();
        let dictionary = NSDictionary::from_slices(
            &keys.iter().map(|v| &**v).collect::<Vec<_>>(),
            &values.iter().map(|v| &**v).collect::<Vec<_>>(),
        );
        // Notification APIs erase dictionary generics; keys and values are immutable NSString objects.
        let dictionary: Retained<NSDictionary> = unsafe { Retained::cast_unchecked(dictionary) };
        unsafe {
            NSDistributedNotificationCenter::defaultCenter()
                .postNotificationName_object_userInfo_deliverImmediately(
                    &NSString::from_str("com.spotify.client.PlaybackStateChanged"),
                    None,
                    Some(&dictionary),
                    true,
                );
        }
    }
    *guard = Some(state);
}
