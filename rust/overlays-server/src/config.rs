use std::env;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    pub pipe_name: String,
    pub pipe_path: String,
}

impl Config {
    pub fn from_env() -> Self {
        let pipe_name = env::var("OVERLAY_PIPE_NAME")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| "overlay_manager".to_string());

        Self {
            pipe_path: format!(r"\\.\pipe\{pipe_name}"),
            pipe_name,
        }
    }
}
