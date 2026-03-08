#[cfg(not(windows))]
fn main() {
    eprintln!("This application is designed to run on Windows only.");
    std::process::exit(1);
}

#[cfg(windows)]
fn main() {
    if let Err(err) = overlays_server::server::run_console() {
        eprintln!("{err}");
        std::process::exit(1);
    }
}
