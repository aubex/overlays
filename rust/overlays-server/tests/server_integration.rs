#![cfg(windows)]

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use overlays_server::{Config, OverlayServer};
use serde_json::{Value, json};
use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE, HANDLE};
use windows::Win32::Storage::FileSystem::{
    CreateFileW, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE, OPEN_EXISTING, ReadFile, WriteFile,
};
use windows::Win32::System::Pipes::{
    PIPE_READMODE_MESSAGE, SetNamedPipeHandleState, WaitNamedPipeW,
};
use windows::core::PCWSTR;

fn test_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn idle_client_does_not_block_second_client() {
    let _guard = test_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let config = unique_config("multi_client");
    let pipe_path = config.pipe_path.clone();
    let mut server = OverlayServer::new(config);
    server.start().unwrap();
    wait_for_pipe(&pipe_path);

    let client_one = PipeClient::connect(&pipe_path);
    let client_two = PipeClient::connect(&pipe_path);

    let response = client_two.send_json(json!({
        "command": "create_countdown",
        "args": {"message_text": "parallel", "countdown_seconds": 5}
    }));
    assert_eq!(response["status"], "success");
    assert_eq!(response["window_id"], 1);

    let closed = client_two.send_json(json!({
        "command": "close_window",
        "args": {"window_id": 1}
    }));
    assert_eq!(
        closed,
        json!({"status":"success","message":"Window 1 closed"})
    );

    drop(client_one);
    drop(client_two);
    server.shutdown();
}

#[test]
fn invalid_json_only_breaks_the_bad_request() {
    let _guard = test_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let config = unique_config("invalid_json");
    let pipe_path = config.pipe_path.clone();
    let mut server = OverlayServer::new(config);
    server.start().unwrap();
    wait_for_pipe(&pipe_path);

    let client = PipeClient::connect(&pipe_path);
    let invalid = client.send_bytes(br#"{"command":"oops""#);
    assert_eq!(invalid, json!({"status":"error","message":"Invalid JSON"}));

    let valid = client.send_json(json!({
        "command": "create_elapsed_time",
        "args": {"message_text": "still alive"}
    }));
    assert_eq!(valid, json!({"status":"success","window_id":1}));

    drop(client);
    server.shutdown();
}

#[test]
fn invalid_durations_only_break_the_bad_request() {
    let _guard = test_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());

    assert_invalid_duration_recovery(
        "highlight_duration",
        json!({
            "command": "create_highlight",
            "args": {"rect": [0, 0, 10, 10], "timeout_seconds": 1e20}
        }),
        json!({"status":"error","message":"Invalid timeout_seconds"}),
    );
    assert_invalid_duration_recovery(
        "countdown_duration",
        json!({
            "command": "create_countdown",
            "args": {"message_text": "bad", "countdown_seconds": 1e20}
        }),
        json!({"status":"error","message":"Invalid countdown_seconds"}),
    );
    assert_invalid_duration_recovery(
        "qrcode_duration",
        json!({
            "command": "create_qrcode_window",
            "args": {"data": "bad", "duration": 1e20, "caption": "Scan"}
        }),
        json!({"status":"error","message":"Invalid duration"}),
    );
    assert_invalid_duration_recovery(
        "break_duration",
        json!({
            "command": "take_break",
            "args": {"duration_seconds": 1e20}
        }),
        json!({"status":"error","message":"Invalid duration_seconds"}),
    );
}

#[test]
fn shutdown_with_idle_client_completes_promptly() {
    let _guard = test_lock()
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let config = unique_config("shutdown_idle");
    let pipe_path = config.pipe_path.clone();
    let mut server = OverlayServer::new(config);
    server.start().unwrap();
    wait_for_pipe(&pipe_path);

    let client = PipeClient::connect(&pipe_path);

    let started = Instant::now();
    server.shutdown();
    assert!(
        started.elapsed() < Duration::from_secs(2),
        "shutdown took too long with an idle client connected"
    );

    drop(client);
}

fn assert_invalid_duration_recovery(prefix: &str, invalid_command: Value, expected_error: Value) {
    let config = unique_config(prefix);
    let pipe_path = config.pipe_path.clone();
    let mut server = OverlayServer::new(config);
    server.start().unwrap();
    wait_for_pipe(&pipe_path);

    let client = PipeClient::connect(&pipe_path);
    let invalid = client.send_json(invalid_command);
    assert_eq!(invalid, expected_error);

    let valid = client.send_json(json!({
        "command": "create_elapsed_time",
        "args": {"message_text": "still alive"}
    }));
    assert_eq!(valid, json!({"status":"success","window_id":1}));

    drop(client);
    server.shutdown();
}

fn unique_config(prefix: &str) -> Config {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let pipe_name = format!("overlay_manager_{prefix}_{suffix}");
    Config {
        pipe_path: format!(r"\\.\pipe\{pipe_name}"),
        pipe_name,
    }
}

fn wait_for_pipe(pipe_path: &str) {
    let wide = to_wide(pipe_path);
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    while std::time::Instant::now() < deadline {
        if unsafe { WaitNamedPipeW(PCWSTR(wide.as_ptr()), 100).as_bool() } {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    panic!("Timed out waiting for pipe {pipe_path}");
}

struct PipeClient {
    handle: HANDLE,
}

impl PipeClient {
    fn connect(pipe_path: &str) -> Self {
        wait_for_pipe(pipe_path);
        let wide = to_wide(pipe_path);
        let handle = unsafe {
            CreateFileW(
                PCWSTR(wide.as_ptr()),
                GENERIC_READ.0 | GENERIC_WRITE.0,
                FILE_SHARE_MODE(0),
                None,
                OPEN_EXISTING,
                FILE_FLAGS_AND_ATTRIBUTES(0),
                None,
            )
        }
        .expect("failed to connect to pipe");

        let mode = PIPE_READMODE_MESSAGE;
        unsafe {
            SetNamedPipeHandleState(handle, Some(&mode), None, None)
                .expect("failed to set pipe mode");
        }

        Self { handle }
    }

    fn send_json(&self, value: Value) -> Value {
        self.send_bytes(&serde_json::to_vec(&value).unwrap())
    }

    fn send_bytes(&self, bytes: &[u8]) -> Value {
        let mut bytes_written = 0_u32;
        unsafe { WriteFile(self.handle, Some(bytes), Some(&mut bytes_written), None) }
            .expect("failed to write request");

        let mut buffer = vec![0_u8; 65_536];
        let mut bytes_read = 0_u32;
        unsafe {
            ReadFile(
                self.handle,
                Some(buffer.as_mut_slice()),
                Some(&mut bytes_read),
                None,
            )
        }
        .expect("failed to read response");

        serde_json::from_slice(&buffer[..bytes_read as usize]).unwrap()
    }
}

impl Drop for PipeClient {
    fn drop(&mut self) {
        let _ = unsafe { CloseHandle(self.handle) };
    }
}

fn to_wide(value: &str) -> Vec<u16> {
    OsStr::new(value)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}
