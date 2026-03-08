use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::Duration;

use crate::config::Config;
use crate::ipc::ListenerRuntime;
use crate::state::StateActor;
use crate::ui::UiRuntime;

pub struct OverlayServer {
    config: Config,
    runtime: Option<Runtime>,
}

struct Runtime {
    shutdown: Arc<AtomicBool>,
    ui: UiRuntime,
    actor: StateActor,
    listener: ListenerRuntime,
}

impl OverlayServer {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            runtime: None,
        }
    }

    pub fn start(&mut self) -> Result<(), String> {
        if self.runtime.is_some() {
            return Ok(());
        }

        let shutdown = Arc::new(AtomicBool::new(false));
        let ui = crate::ui::spawn_ui_thread()?;
        let actor = StateActor::start(ui.bridge());
        let listener =
            crate::ipc::spawn_listener(self.config.clone(), actor.sender.clone(), shutdown.clone());

        self.runtime = Some(Runtime {
            shutdown,
            ui,
            actor,
            listener,
        });
        Ok(())
    }

    pub fn shutdown(&mut self) {
        let Some(mut runtime) = self.runtime.take() else {
            return;
        };

        runtime.shutdown.store(true, Ordering::SeqCst);
        runtime.listener.shutdown();
        runtime.actor.shutdown();
        runtime.ui.shutdown();
    }

    pub fn pipe_path(&self) -> &str {
        &self.config.pipe_path
    }
}

impl Drop for OverlayServer {
    fn drop(&mut self) {
        self.shutdown();
    }
}

pub fn run_console() -> Result<(), String> {
    let config = Config::from_env();
    let mut server = OverlayServer::new(config);
    server.start()?;

    println!("overlays-server v{}", env!("CARGO_PKG_VERSION"));
    println!("====================");
    println!("Starting overlay server...");
    println!("Overlay server initialized successfully");
    println!("Named pipe server: {}", server.pipe_path());
    println!("Application ready - overlay windows can now be created");
    println!("Press Ctrl+C to shutdown gracefully");

    let shutdown = Arc::new(AtomicBool::new(false));
    let signal = shutdown.clone();
    ctrlc::set_handler(move || {
        signal.store(true, Ordering::SeqCst);
    })
    .map_err(|err| err.to_string())?;

    while !shutdown.load(Ordering::SeqCst) {
        thread::sleep(Duration::from_millis(200));
    }

    server.shutdown();
    Ok(())
}
