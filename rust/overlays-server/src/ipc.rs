#[cfg(not(windows))]
compile_error!("The IPC module is Windows-only.");

use std::ffi::OsStr;
use std::os::windows::ffi::OsStrExt;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use windows::Win32::Foundation::{
    CloseHandle, DUPLICATE_SAME_ACCESS, DuplicateHandle, ERROR_BROKEN_PIPE, ERROR_MORE_DATA,
    ERROR_NO_DATA, ERROR_OPERATION_ABORTED, ERROR_PIPE_CONNECTED, ERROR_PIPE_LISTENING, HANDLE,
};
use windows::Win32::Storage::FileSystem::{
    FlushFileBuffers, PIPE_ACCESS_DUPLEX, ReadFile, WriteFile,
};
use windows::Win32::System::IO::CancelSynchronousIo;
use windows::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, PIPE_NOWAIT, PIPE_READMODE_MESSAGE,
    PIPE_TYPE_MESSAGE, PIPE_UNLIMITED_INSTANCES, PIPE_WAIT, SetNamedPipeHandleState,
};
use windows::Win32::System::Threading::{GetCurrentProcess, GetCurrentThread};
use windows::core::PCWSTR;

use crate::config::Config;
use crate::protocol::{COMMAND_TIMEOUT, OverlayResponse, PIPE_BUFFER_SIZE, parse_message};
use crate::state::ActorMessage;

const POLL_INTERVAL: Duration = Duration::from_millis(50);

pub struct ListenerRuntime {
    join_handle: Option<JoinHandle<()>>,
    session_threads: Arc<Mutex<Vec<SessionThread>>>,
}

struct SessionThread {
    join_handle: JoinHandle<()>,
    cancel_handle: Option<ThreadHandle>,
}

struct ThreadHandle(HANDLE);

unsafe impl Send for ThreadHandle {}

impl ThreadHandle {
    fn duplicate_current() -> Option<Self> {
        let current_process = unsafe { GetCurrentProcess() };
        let mut duplicated = HANDLE::default();
        let duplicated_ok = unsafe {
            DuplicateHandle(
                current_process,
                GetCurrentThread(),
                current_process,
                &mut duplicated,
                0,
                false,
                DUPLICATE_SAME_ACCESS,
            )
        };

        if duplicated_ok.is_ok() {
            Some(Self(duplicated))
        } else {
            None
        }
    }

    fn cancel_sync_io(&self) {
        let _ = unsafe { CancelSynchronousIo(self.0) };
    }
}

impl Drop for ThreadHandle {
    fn drop(&mut self) {
        let _ = unsafe { CloseHandle(self.0) };
    }
}

impl ListenerRuntime {
    pub fn shutdown(&mut self) {
        cancel_all_sessions(&self.session_threads);
        if let Some(join_handle) = self.join_handle.take() {
            let _ = join_handle.join();
        }
        cancel_all_sessions(&self.session_threads);
        reap_finished_sessions(&self.session_threads);
        join_all_sessions(&self.session_threads);
    }

    #[cfg(test)]
    fn session_thread_count(&self) -> usize {
        self.session_threads
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
            .len()
    }
}

pub fn spawn_listener(
    config: Config,
    actor_sender: mpsc::Sender<ActorMessage>,
    shutdown: Arc<AtomicBool>,
) -> ListenerRuntime {
    let session_threads = Arc::new(Mutex::new(Vec::new()));
    let thread_registry = session_threads.clone();
    let next_session_id = Arc::new(AtomicU64::new(1));
    let join_handle = thread::spawn(move || {
        listener_loop(
            config,
            actor_sender,
            shutdown,
            thread_registry,
            next_session_id,
        );
    });

    ListenerRuntime {
        join_handle: Some(join_handle),
        session_threads,
    }
}

fn listener_loop(
    config: Config,
    actor_sender: mpsc::Sender<ActorMessage>,
    shutdown: Arc<AtomicBool>,
    session_threads: Arc<Mutex<Vec<SessionThread>>>,
    next_session_id: Arc<AtomicU64>,
) {
    while !shutdown.load(Ordering::SeqCst) {
        reap_finished_sessions(&session_threads);

        let Some(pipe_handle) = create_pipe_instance(&config.pipe_path) else {
            thread::sleep(Duration::from_millis(250));
            continue;
        };

        match wait_for_client(pipe_handle.raw(), &shutdown, &session_threads) {
            ConnectResult::Connected => {
                if shutdown.load(Ordering::SeqCst) {
                    continue;
                }

                let _session_id = next_session_id.fetch_add(1, Ordering::Relaxed);
                let actor_sender = actor_sender.clone();
                let shutdown = shutdown.clone();
                let (ready_tx, ready_rx) = mpsc::channel();
                let join_handle = thread::spawn(move || {
                    let _ = ready_tx.send(ThreadHandle::duplicate_current());
                    session_loop(pipe_handle, actor_sender, shutdown)
                });
                let cancel_handle = ready_rx.recv().ok().flatten();
                let mut sessions = session_threads
                    .lock()
                    .unwrap_or_else(|poison| poison.into_inner());
                sessions.push(SessionThread {
                    join_handle,
                    cancel_handle,
                });
            }
            ConnectResult::Shutdown | ConnectResult::Failed => {}
        }
    }
}

fn session_loop(
    pipe_handle: PipeHandle,
    actor_sender: mpsc::Sender<ActorMessage>,
    shutdown: Arc<AtomicBool>,
) {
    if !set_blocking_read_mode(pipe_handle.raw()) {
        return;
    }

    while !shutdown.load(Ordering::SeqCst) {
        let message = match read_pipe_message(pipe_handle.raw()) {
            SessionRead::Message(message) => message,
            SessionRead::Disconnected | SessionRead::Shutdown => break,
        };

        let response = handle_message(&message, &actor_sender);
        if !write_pipe_message(pipe_handle.raw(), &response) {
            break;
        }
    }
}

fn handle_message(message: &[u8], actor_sender: &mpsc::Sender<ActorMessage>) -> OverlayResponse {
    let command = match parse_message(message) {
        Ok(command) => command,
        Err(response) => return response,
    };

    let (reply_tx, reply_rx) = mpsc::channel();
    if actor_sender
        .send(ActorMessage::Execute {
            command,
            reply: reply_tx,
        })
        .is_err()
    {
        return OverlayResponse::internal_error("worker");
    }

    match reply_rx.recv_timeout(COMMAND_TIMEOUT) {
        Ok(response) => response,
        Err(_) => OverlayResponse::timeout(),
    }
}

fn create_pipe_instance(pipe_path: &str) -> Option<PipeHandle> {
    let wide_pipe_path = to_wide(pipe_path);
    let handle = unsafe {
        CreateNamedPipeW(
            PCWSTR(wide_pipe_path.as_ptr()),
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_NOWAIT,
            PIPE_UNLIMITED_INSTANCES,
            PIPE_BUFFER_SIZE as u32,
            PIPE_BUFFER_SIZE as u32,
            0,
            None,
        )
    };

    if handle.is_invalid() {
        None
    } else {
        Some(PipeHandle::new(handle))
    }
}

fn set_blocking_read_mode(handle: HANDLE) -> bool {
    let mode = PIPE_READMODE_MESSAGE | PIPE_WAIT;
    unsafe { SetNamedPipeHandleState(handle, Some(&mode), None, None) }.is_ok()
}

fn wait_for_client(
    handle: HANDLE,
    shutdown: &AtomicBool,
    session_threads: &Mutex<Vec<SessionThread>>,
) -> ConnectResult {
    while !shutdown.load(Ordering::SeqCst) {
        reap_finished_sessions(session_threads);
        match unsafe { ConnectNamedPipe(handle, None) } {
            Ok(()) => return ConnectResult::Connected,
            Err(_) => {
                let error = unsafe { windows::Win32::Foundation::GetLastError() };
                if error == ERROR_PIPE_CONNECTED || error == ERROR_NO_DATA {
                    return ConnectResult::Connected;
                }
                if error == ERROR_PIPE_LISTENING {
                    thread::sleep(POLL_INTERVAL);
                    continue;
                }
                return ConnectResult::Failed;
            }
        }
    }
    let _ = unsafe { DisconnectNamedPipe(handle) };
    ConnectResult::Shutdown
}

fn read_pipe_message(handle: HANDLE) -> SessionRead {
    let mut message = Vec::new();
    let mut buffer = vec![0_u8; PIPE_BUFFER_SIZE];

    loop {
        let mut bytes_read = 0_u32;
        let read_result = unsafe {
            ReadFile(
                handle,
                Some(buffer.as_mut_slice()),
                Some(&mut bytes_read),
                None,
            )
        };

        if let Err(_) = read_result {
            let error = unsafe { windows::Win32::Foundation::GetLastError() };
            if error == ERROR_MORE_DATA {
                message.extend_from_slice(&buffer[..bytes_read as usize]);
                continue;
            }
            if error == ERROR_OPERATION_ABORTED {
                return SessionRead::Shutdown;
            }
            if error == ERROR_BROKEN_PIPE || error == ERROR_NO_DATA {
                return SessionRead::Disconnected;
            }
            return SessionRead::Disconnected;
        }

        if bytes_read == 0 {
            return SessionRead::Disconnected;
        }

        message.extend_from_slice(&buffer[..bytes_read as usize]);
        return SessionRead::Message(message);
    }
}

fn write_pipe_message(handle: HANDLE, response: &OverlayResponse) -> bool {
    let payload = match serde_json::to_vec(response) {
        Ok(payload) => payload,
        Err(_) => return false,
    };
    let mut bytes_written = 0_u32;
    if unsafe {
        WriteFile(
            handle,
            Some(payload.as_slice()),
            Some(&mut bytes_written),
            None,
        )
    }
    .is_err()
    {
        return false;
    }
    let _ = unsafe { FlushFileBuffers(handle) };
    true
}

fn cancel_all_sessions(session_threads: &Mutex<Vec<SessionThread>>) {
    let sessions = session_threads
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    for session in sessions.iter() {
        if let Some(handle) = &session.cancel_handle {
            handle.cancel_sync_io();
        }
    }
}

fn reap_finished_sessions(session_threads: &Mutex<Vec<SessionThread>>) {
    let mut sessions = session_threads
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    let mut pending = Vec::with_capacity(sessions.len());

    while let Some(session) = sessions.pop() {
        if session.join_handle.is_finished() {
            let _ = session.join_handle.join();
        } else {
            pending.push(session);
        }
    }

    pending.reverse();
    *sessions = pending;
}

fn join_all_sessions(session_threads: &Mutex<Vec<SessionThread>>) {
    let mut sessions = session_threads
        .lock()
        .unwrap_or_else(|poison| poison.into_inner());
    while let Some(session) = sessions.pop() {
        let _ = session.join_handle.join();
    }
}

enum ConnectResult {
    Connected,
    Shutdown,
    Failed,
}

enum SessionRead {
    Message(Vec<u8>),
    Disconnected,
    Shutdown,
}

struct PipeHandle {
    raw: HANDLE,
}

unsafe impl Send for PipeHandle {}

impl PipeHandle {
    fn new(handle: HANDLE) -> Self {
        Self { raw: handle }
    }

    fn raw(&self) -> HANDLE {
        self.raw
    }
}

impl Drop for PipeHandle {
    fn drop(&mut self) {
        let _ = unsafe { DisconnectNamedPipe(self.raw) };
        let _ = unsafe { CloseHandle(self.raw) };
    }
}

fn to_wide(value: &str) -> Vec<u16> {
    OsStr::new(value)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::{Arc, Mutex, OnceLock, mpsc};
    use std::thread::{self, JoinHandle};
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    use serde_json::json;
    use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE, HANDLE};
    use windows::Win32::Storage::FileSystem::{
        CreateFileW, FILE_FLAGS_AND_ATTRIBUTES, FILE_SHARE_MODE, OPEN_EXISTING, ReadFile,
        WriteFile,
    };
    use windows::Win32::System::Pipes::{
        PIPE_READMODE_MESSAGE, SetNamedPipeHandleState, WaitNamedPipeW,
    };
    use windows::core::PCWSTR;

    use super::{spawn_listener, to_wide};
    use crate::config::Config;
    use crate::protocol::OverlayResponse;
    use crate::state::ActorMessage;

    fn test_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    #[test]
    fn session_threads_reap_after_disconnect_churn() {
        let _guard = test_lock()
            .lock()
            .unwrap_or_else(|poison| poison.into_inner());
        let config = unique_config("listener_churn");
        let shutdown = Arc::new(AtomicBool::new(false));
        let (actor_sender, actor_thread) = spawn_mock_actor();
        let mut listener = spawn_listener(config.clone(), actor_sender.clone(), shutdown.clone());
        wait_for_pipe(&config.pipe_path);

        for _ in 0..40 {
            let client = PipeClient::connect(&config.pipe_path);
            drop(client);
        }

        assert!(
            wait_until(Duration::from_secs(3), || listener.session_thread_count() == 0),
            "session threads were not reaped after disconnect churn"
        );

        let client = PipeClient::connect(&config.pipe_path);
        let response = client.send_json(json!({
            "command": "create_elapsed_time",
            "args": {"message_text": "still alive"}
        }));
        assert_eq!(response, json!({"status":"success","window_id":1}));

        drop(client);
        shutdown.store(true, Ordering::SeqCst);
        listener.shutdown();
        let _ = actor_sender.send(ActorMessage::Shutdown);
        let _ = actor_thread.join();
    }

    fn spawn_mock_actor() -> (mpsc::Sender<ActorMessage>, JoinHandle<()>) {
        let (actor_sender, actor_receiver) = mpsc::channel::<ActorMessage>();
        let join_handle = thread::spawn(move || {
            loop {
                match actor_receiver.recv() {
                    Ok(ActorMessage::Execute { reply, .. }) => {
                        let _ = reply.send(OverlayResponse::success_window(1));
                    }
                    Ok(ActorMessage::Shutdown) | Err(_) => break,
                }
            }
        });

        (actor_sender, join_handle)
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
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if unsafe { WaitNamedPipeW(PCWSTR(wide.as_ptr()), 100).as_bool() } {
                return;
            }
            thread::sleep(Duration::from_millis(25));
        }
        panic!("Timed out waiting for pipe {pipe_path}");
    }

    fn wait_until(timeout: Duration, check: impl Fn() -> bool) -> bool {
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if check() {
                return true;
            }
            thread::sleep(Duration::from_millis(25));
        }
        check()
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

        fn send_json(&self, value: serde_json::Value) -> serde_json::Value {
            let payload = serde_json::to_vec(&value).unwrap();
            let mut bytes_written = 0_u32;
            unsafe { WriteFile(self.handle, Some(payload.as_slice()), Some(&mut bytes_written), None) }
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
}
