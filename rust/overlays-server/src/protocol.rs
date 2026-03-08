use std::time::Duration;

use serde::Serialize;
use serde_json::Value;

pub const PIPE_BUFFER_SIZE: usize = 65_536;
pub const COMMAND_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WindowIdArg {
    pub provided: bool,
    pub numeric: Option<u32>,
    pub display: String,
}

impl WindowIdArg {
    pub fn missing() -> Self {
        Self {
            provided: false,
            numeric: None,
            display: String::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum ParsedCommand {
    CreateHighlight {
        rect: Option<[i32; 4]>,
        timeout_seconds: f64,
    },
    CreateCountdown {
        message_text: String,
        countdown_seconds: f64,
    },
    CreateElapsedTime {
        message_text: String,
    },
    CreateQrCodeWindow {
        data: Value,
        duration_seconds: f64,
        caption: String,
    },
    CloseWindow {
        window_id: WindowIdArg,
    },
    UpdateWindowMessage {
        window_id: WindowIdArg,
        new_message: Option<String>,
    },
    TakeBreak {
        duration_seconds: f64,
        duration_display: String,
    },
    CancelBreak,
}

impl ParsedCommand {
    pub fn name(&self) -> &'static str {
        match self {
            Self::CreateHighlight { .. } => "create_highlight",
            Self::CreateCountdown { .. } => "create_countdown",
            Self::CreateElapsedTime { .. } => "create_elapsed_time",
            Self::CreateQrCodeWindow { .. } => "create_qrcode_window",
            Self::CloseWindow { .. } => "close_window",
            Self::UpdateWindowMessage { .. } => "update_window_message",
            Self::TakeBreak { .. } => "take_break",
            Self::CancelBreak => "cancel_break",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OverlayResponse {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub window_id: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
}

impl OverlayResponse {
    pub fn success_window(window_id: u32) -> Self {
        Self {
            status: "success".to_string(),
            window_id: Some(window_id),
            message: None,
            reason: None,
        }
    }

    pub fn success_message(message: impl Into<String>) -> Self {
        Self {
            status: "success".to_string(),
            window_id: None,
            message: Some(message.into()),
            reason: None,
        }
    }

    pub fn error(message: impl Into<String>) -> Self {
        Self {
            status: "error".to_string(),
            window_id: None,
            message: Some(message.into()),
            reason: None,
        }
    }

    pub fn ignored(reason: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            status: "ignored".to_string(),
            window_id: None,
            message: Some(message.into()),
            reason: Some(reason.into()),
        }
    }

    pub fn internal_error(command_name: &str) -> Self {
        Self::error(format!("Command '{command_name}' failed: internal error"))
    }

    pub fn timeout() -> Self {
        Self::error("Command timed out")
    }

    pub fn invalid_json() -> Self {
        Self::error("Invalid JSON")
    }
}

pub fn parse_message(message: &[u8]) -> Result<ParsedCommand, OverlayResponse> {
    let root: Value =
        serde_json::from_slice(message).map_err(|_| OverlayResponse::invalid_json())?;
    let command_value = root.get("command").cloned().unwrap_or(Value::Null);
    let args = root
        .get("args")
        .cloned()
        .unwrap_or_else(|| Value::Object(Default::default()));

    let command_name = display_json_value(&command_value, false);
    let Some(command) = command_value.as_str() else {
        return Err(OverlayResponse::error(format!(
            "Unknown command {command_name}"
        )));
    };

    match command {
        "create_highlight" => Ok(ParsedCommand::CreateHighlight {
            rect: parse_rect_arg(&args, "rect"),
            timeout_seconds: get_duration_or_default(
                &args,
                "timeout_seconds",
                3.0,
                "timeout_seconds",
            )?,
        }),
        "create_countdown" => Ok(ParsedCommand::CreateCountdown {
            message_text: get_string_or_default(&args, "message_text", ""),
            countdown_seconds: get_duration_or_default(
                &args,
                "countdown_seconds",
                3.0,
                "countdown_seconds",
            )?,
        }),
        "create_elapsed_time" => Ok(ParsedCommand::CreateElapsedTime {
            message_text: get_string_or_default(&args, "message_text", ""),
        }),
        "create_qrcode_window" => Ok(ParsedCommand::CreateQrCodeWindow {
            data: get_value_or_default(&args, "data", Value::String(String::new())),
            duration_seconds: get_duration_or_default(&args, "duration", 5.0, "duration")?,
            caption: get_string_or_default(&args, "caption", ""),
        }),
        "close_window" => Ok(ParsedCommand::CloseWindow {
            window_id: parse_window_id_arg(&args, "window_id"),
        }),
        "update_window_message" => Ok(ParsedCommand::UpdateWindowMessage {
            window_id: parse_window_id_arg(&args, "window_id"),
            new_message: parse_non_empty_message(&args, "new_message"),
        }),
        "take_break" => Ok(ParsedCommand::TakeBreak {
            duration_seconds: get_duration_or_default(
                &args,
                "duration_seconds",
                0.0,
                "duration_seconds",
            )?,
            duration_display: get_duration_display_or_default(&args, "duration_seconds", "0")?,
        }),
        "cancel_break" => Ok(ParsedCommand::CancelBreak),
        _ => Err(OverlayResponse::error(format!(
            "Unknown command {command_name}"
        ))),
    }
}

fn get_arg<'a>(args: &'a Value, key: &str) -> Option<&'a Value> {
    args.as_object().and_then(|map| map.get(key))
}

fn get_value_or_default(args: &Value, key: &str, default: Value) -> Value {
    get_arg(args, key).cloned().unwrap_or(default)
}

fn get_string_or_default(args: &Value, key: &str, default: &str) -> String {
    match get_arg(args, key) {
        Some(Value::String(value)) => value.clone(),
        Some(value) => display_json_value(value, true),
        None => default.to_string(),
    }
}

fn get_duration_or_default(
    args: &Value,
    key: &str,
    default: f64,
    field_name: &str,
) -> Result<f64, OverlayResponse> {
    match get_arg(args, key).and_then(Value::as_f64) {
        Some(value) => validate_duration_seconds(value, field_name),
        None => Ok(default),
    }
}

fn get_duration_display_or_default(
    args: &Value,
    key: &str,
    default: &str,
) -> Result<String, OverlayResponse> {
    let Some(value) = get_arg(args, key) else {
        return Ok(default.to_string());
    };
    let Some(number) = value.as_f64() else {
        return Ok(default.to_string());
    };
    let normalized = validate_duration_seconds(number, key)?;
    if normalized == 0.0 && number < 0.0 {
        return Ok("0".to_string());
    }

    match value {
        Value::Number(number) => Ok(number.to_string()),
        _ => Ok(default.to_string()),
    }
}

fn parse_rect_arg(args: &Value, key: &str) -> Option<[i32; 4]> {
    let values = get_arg(args, key)?.as_array()?;
    if values.len() != 4 {
        return None;
    }
    let mut rect = [0_i32; 4];
    for (index, value) in values.iter().enumerate() {
        let number = value.as_i64()?;
        rect[index] = i32::try_from(number).ok()?;
    }
    Some(rect)
}

fn parse_window_id_arg(args: &Value, key: &str) -> WindowIdArg {
    let Some(value) = get_arg(args, key) else {
        return WindowIdArg::missing();
    };
    if !is_truthy(value) {
        return WindowIdArg::missing();
    }

    let numeric = value
        .as_u64()
        .and_then(|number| u32::try_from(number).ok())
        .filter(|number| *number > 0);

    WindowIdArg {
        provided: true,
        numeric,
        display: display_json_value(value, true),
    }
}

fn parse_non_empty_message(args: &Value, key: &str) -> Option<String> {
    let value = get_arg(args, key)?;
    if !is_truthy(value) {
        return None;
    }
    Some(display_json_value(value, true))
}

fn is_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(number) => number.as_f64().is_some_and(|value| value != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(values) => !values.is_empty(),
        Value::Object(values) => !values.is_empty(),
    }
}

fn display_json_value(value: &Value, unquote_strings: bool) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::String(text) if unquote_strings => text.clone(),
        Value::String(text) => text.clone(),
        _ => value.to_string(),
    }
}

pub(crate) fn validate_duration_seconds(
    seconds: f64,
    field_name: &str,
) -> Result<f64, OverlayResponse> {
    let normalized = seconds.max(0.0);
    if !normalized.is_finite() {
        return Err(OverlayResponse::error(format!("Invalid {field_name}")));
    }

    match Duration::try_from_secs_f64(normalized) {
        Ok(_) => Ok(normalized),
        Err(_) => Err(OverlayResponse::error(format!("Invalid {field_name}"))),
    }
}

#[cfg(test)]
mod tests {
    use super::{OverlayResponse, ParsedCommand, WindowIdArg, parse_message};

    #[test]
    fn parses_create_countdown_defaults() {
        let command = parse_message(br#"{"command":"create_countdown","args":{}}"#).unwrap();
        assert_eq!(
            command,
            ParsedCommand::CreateCountdown {
                message_text: String::new(),
                countdown_seconds: 3.0,
            }
        );
    }

    #[test]
    fn missing_highlight_rect_stays_parseable() {
        let command = parse_message(br#"{"command":"create_highlight","args":{}}"#).unwrap();
        assert_eq!(
            command,
            ParsedCommand::CreateHighlight {
                rect: None,
                timeout_seconds: 3.0,
            }
        );
    }

    #[test]
    fn empty_update_message_is_missing() {
        let command = parse_message(
            br#"{"command":"update_window_message","args":{"window_id":1,"new_message":""}}"#,
        )
        .unwrap();
        assert_eq!(
            command,
            ParsedCommand::UpdateWindowMessage {
                window_id: WindowIdArg {
                    provided: true,
                    numeric: Some(1),
                    display: "1".to_string(),
                },
                new_message: None,
            }
        );
    }

    #[test]
    fn unknown_command_uses_exact_error_shape() {
        let response = parse_message(br#"{"command":"nope","args":{}}"#).unwrap_err();
        assert_eq!(response, OverlayResponse::error("Unknown command nope"));
    }

    #[test]
    fn invalid_json_uses_structured_error() {
        let response = parse_message(br#"{"command":"oops""#).unwrap_err();
        assert_eq!(response, OverlayResponse::invalid_json());
    }

    #[test]
    fn oversized_duration_is_rejected() {
        let response = parse_message(
            br#"{"command":"create_countdown","args":{"countdown_seconds":1e20}}"#,
        )
        .unwrap_err();
        assert_eq!(response, OverlayResponse::error("Invalid countdown_seconds"));
    }

    #[test]
    fn negative_break_duration_is_normalized_for_display() {
        let command =
            parse_message(br#"{"command":"take_break","args":{"duration_seconds":-5}}"#).unwrap();
        assert_eq!(
            command,
            ParsedCommand::TakeBreak {
                duration_seconds: 0.0,
                duration_display: "0".to_string(),
            }
        );
    }
}
