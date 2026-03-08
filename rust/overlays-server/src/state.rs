use std::collections::HashMap;
use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use qrcode::{Color, EcLevel, QrCode};
use rand::Rng;
use serde_json::Value;

use crate::protocol::{OverlayResponse, ParsedCommand, validate_duration_seconds};
use crate::ui::UiBridge;

const TICK_INTERVAL: Duration = Duration::from_millis(100);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HighlightSnapshot {
    pub id: u32,
    pub coords: (i32, i32, i32, i32),
    pub color: (u8, u8, u8),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CountdownVisualState {
    Countdown { remaining: u64 },
    Elapsed { elapsed: u64 },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CountdownSnapshot {
    pub id: u32,
    pub message: String,
    pub order: u64,
    pub visual: CountdownVisualState,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QrCodeSnapshot {
    pub id: u32,
    pub matrix: Vec<Vec<bool>>,
    pub qr_size: i32,
    pub pix_per_mod: i32,
    pub padding: i32,
    pub caption: String,
    pub order: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct OverlaySnapshot {
    pub rectangles: Vec<HighlightSnapshot>,
    pub countdowns: Vec<CountdownSnapshot>,
    pub qrcodes: Vec<QrCodeSnapshot>,
}

#[derive(Debug)]
pub enum ActorMessage {
    Execute {
        command: ParsedCommand,
        reply: Sender<OverlayResponse>,
    },
    Shutdown,
}

#[derive(Debug)]
pub struct StateActor {
    pub sender: Sender<ActorMessage>,
    join_handle: Option<JoinHandle<()>>,
}

impl StateActor {
    pub fn start(ui_bridge: UiBridge) -> Self {
        let (sender, receiver) = std::sync::mpsc::channel();
        let join_handle = thread::spawn(move || run_actor(receiver, ui_bridge));
        Self {
            sender,
            join_handle: Some(join_handle),
        }
    }

    pub fn shutdown(&mut self) {
        let _ = self.sender.send(ActorMessage::Shutdown);
        if let Some(join_handle) = self.join_handle.take() {
            let _ = join_handle.join();
        }
    }
}

#[derive(Debug, Clone)]
struct HighlightEntry {
    id: u32,
    coords: (i32, i32, i32, i32),
    color: (u8, u8, u8),
    expires_at: Instant,
}

#[derive(Debug, Clone)]
enum CountdownEntryKind {
    Countdown { end_time: Instant, remaining: u64 },
    Elapsed { start_time: Instant, elapsed: u64 },
}

#[derive(Debug, Clone)]
struct CountdownEntry {
    message: String,
    order: u64,
    kind: CountdownEntryKind,
}

#[derive(Debug, Clone)]
struct QrCodeEntry {
    matrix: Vec<Vec<bool>>,
    qr_size: i32,
    pix_per_mod: i32,
    padding: i32,
    caption: String,
    order: u64,
    expires_at: Instant,
}

#[derive(Debug)]
pub struct OverlayState {
    rectangles: Vec<HighlightEntry>,
    countdowns: HashMap<u32, CountdownEntry>,
    qrcodes: HashMap<u32, QrCodeEntry>,
    next_rect_id: u32,
    next_countdown_id: u32,
    next_qrcode_id: u32,
    qrcode_order: u64,
    countdown_order: u64,
    break_until: Option<Instant>,
}

impl Default for OverlayState {
    fn default() -> Self {
        Self {
            rectangles: Vec::new(),
            countdowns: HashMap::new(),
            qrcodes: HashMap::new(),
            next_rect_id: 1,
            next_countdown_id: 1,
            next_qrcode_id: 1,
            qrcode_order: 0,
            countdown_order: 0,
            break_until: None,
        }
    }
}

impl OverlayState {
    pub fn execute(&mut self, command: ParsedCommand, now: Instant) -> (OverlayResponse, bool) {
        match command {
            ParsedCommand::TakeBreak {
                duration_seconds,
                duration_display,
            } => match duration_from_seconds(duration_seconds, "duration_seconds") {
                Ok(duration) => {
                    self.break_until = Some(now + duration);
                    (
                        OverlayResponse::success_message(format!(
                            "Break started for {duration_display} seconds"
                        )),
                        false,
                    )
                }
                Err(response) => (response, false),
            },
            ParsedCommand::CancelBreak => {
                self.break_until = None;
                (OverlayResponse::success_message("Break canceled"), false)
            }
            other if self.is_break_active(now) => (
                OverlayResponse::ignored("break_active", "Command discarded during break"),
                matches!(
                    other,
                    ParsedCommand::CancelBreak | ParsedCommand::TakeBreak { .. }
                ),
            ),
            ParsedCommand::CreateHighlight {
                rect,
                timeout_seconds,
            } => match (rect, duration_from_seconds(timeout_seconds, "timeout_seconds")) {
                (Some([left, top, right, bottom]), Ok(duration)) => {
                    let window_id =
                        self.add_highlight_window((left, top, right, bottom), duration, now);
                    (OverlayResponse::success_window(window_id), true)
                }
                (Some(_), Err(response)) => (response, false),
                (None, _) => (OverlayResponse::internal_error("create_highlight"), false),
            },
            ParsedCommand::CreateCountdown {
                message_text,
                countdown_seconds,
            } => match duration_from_seconds(countdown_seconds, "countdown_seconds") {
                Ok(duration) => {
                    let window_id = self.add_countdown_window(message_text, duration, now);
                    (OverlayResponse::success_window(window_id), true)
                }
                Err(response) => (response, false),
            },
            ParsedCommand::CreateElapsedTime { message_text } => {
                let window_id = self.add_elapsed_window(message_text, now);
                (OverlayResponse::success_window(window_id), true)
            }
            ParsedCommand::CreateQrCodeWindow {
                data,
                duration_seconds,
                caption,
            } => match duration_from_seconds(duration_seconds, "duration") {
                Ok(duration) => match self.add_qrcode_window(&data, duration, caption, now) {
                    Ok(window_id) => (OverlayResponse::success_window(window_id), true),
                    Err(response) => (response, false),
                },
                Err(response) => (response, false),
            },
            ParsedCommand::CloseWindow { window_id } => {
                if !window_id.provided {
                    return (OverlayResponse::error("Missing window_id"), false);
                }
                if let Some(id) = window_id.numeric {
                    if self.close_window(id) {
                        return (
                            OverlayResponse::success_message(format!("Window {id} closed")),
                            true,
                        );
                    }
                }
                (
                    OverlayResponse::error(format!("Window {} not found", window_id.display)),
                    false,
                )
            }
            ParsedCommand::UpdateWindowMessage {
                window_id,
                new_message,
            } => {
                let Some(new_message) = new_message else {
                    return (
                        OverlayResponse::error("Missing window_id or new_message"),
                        false,
                    );
                };
                if !window_id.provided {
                    return (
                        OverlayResponse::error("Missing window_id or new_message"),
                        false,
                    );
                }
                if let Some(id) = window_id.numeric {
                    if self.update_window(id, new_message) {
                        return (
                            OverlayResponse::success_message(format!("Window {id} updated")),
                            true,
                        );
                    }
                }
                (
                    OverlayResponse::error(format!("Window {} not found", window_id.display)),
                    false,
                )
            }
        }
    }

    pub fn tick(&mut self, now: Instant) -> bool {
        let mut changed = false;

        let before_rectangles = self.rectangles.len();
        self.rectangles.retain(|entry| entry.expires_at > now);
        changed |= before_rectangles != self.rectangles.len();

        let before_qrcodes = self.qrcodes.len();
        self.qrcodes.retain(|_, entry| entry.expires_at > now);
        changed |= before_qrcodes != self.qrcodes.len();

        let mut expired_ids = Vec::new();
        for (id, countdown) in &mut self.countdowns {
            match &mut countdown.kind {
                CountdownEntryKind::Countdown {
                    end_time,
                    remaining,
                } => {
                    let next_remaining = remaining_seconds(*end_time, now);
                    if next_remaining == 0 {
                        expired_ids.push(*id);
                    } else if *remaining != next_remaining {
                        *remaining = next_remaining;
                        changed = true;
                    }
                }
                CountdownEntryKind::Elapsed {
                    start_time,
                    elapsed,
                } => {
                    let next_elapsed = elapsed_seconds(*start_time, now);
                    if *elapsed != next_elapsed {
                        *elapsed = next_elapsed;
                        changed = true;
                    }
                }
            }
        }

        for id in expired_ids {
            self.countdowns.remove(&id);
            changed = true;
        }

        changed
    }

    pub fn snapshot(&self) -> OverlaySnapshot {
        let mut countdowns: Vec<_> = self
            .countdowns
            .iter()
            .map(|(id, entry)| CountdownSnapshot {
                id: *id,
                message: entry.message.clone(),
                order: entry.order,
                visual: match entry.kind {
                    CountdownEntryKind::Countdown { remaining, .. } => {
                        CountdownVisualState::Countdown { remaining }
                    }
                    CountdownEntryKind::Elapsed { elapsed, .. } => {
                        CountdownVisualState::Elapsed { elapsed }
                    }
                },
            })
            .collect();
        countdowns.sort_by_key(|entry| entry.order);

        let mut qrcodes: Vec<_> = self
            .qrcodes
            .iter()
            .map(|(id, entry)| QrCodeSnapshot {
                id: *id,
                matrix: entry.matrix.clone(),
                qr_size: entry.qr_size,
                pix_per_mod: entry.pix_per_mod,
                padding: entry.padding,
                caption: entry.caption.clone(),
                order: entry.order,
            })
            .collect();
        qrcodes.sort_by_key(|entry| entry.order);

        OverlaySnapshot {
            rectangles: self
                .rectangles
                .iter()
                .map(|entry| HighlightSnapshot {
                    id: entry.id,
                    coords: entry.coords,
                    color: entry.color,
                })
                .collect(),
            countdowns,
            qrcodes,
        }
    }

    fn add_highlight_window(
        &mut self,
        rect: (i32, i32, i32, i32),
        timeout: Duration,
        now: Instant,
    ) -> u32 {
        let id = self.next_rect_id;
        self.next_rect_id += 1;
        let mut rng = rand::rng();
        let color = (
            rng.random_range(64..=255),
            rng.random_range(64..=255),
            rng.random_range(64..=255),
        );
        self.rectangles.push(HighlightEntry {
            id,
            coords: rect,
            color,
            expires_at: now + timeout,
        });
        id
    }

    fn add_countdown_window(
        &mut self,
        message_text: String,
        countdown: Duration,
        now: Instant,
    ) -> u32 {
        let id = self.next_countdown_id;
        self.next_countdown_id += 1;
        self.countdown_order += 1;
        let remaining = duration_ceil_seconds(countdown);
        self.countdowns.insert(
            id,
            CountdownEntry {
                message: message_text,
                order: self.countdown_order,
                kind: CountdownEntryKind::Countdown {
                    end_time: now + countdown,
                    remaining,
                },
            },
        );
        id
    }

    fn add_elapsed_window(&mut self, message_text: String, now: Instant) -> u32 {
        let id = self.next_countdown_id;
        self.next_countdown_id += 1;
        self.countdown_order += 1;
        self.countdowns.insert(
            id,
            CountdownEntry {
                message: message_text,
                order: self.countdown_order,
                kind: CountdownEntryKind::Elapsed {
                    start_time: now,
                    elapsed: 0,
                },
            },
        );
        id
    }

    fn add_qrcode_window(
        &mut self,
        data: &Value,
        duration: Duration,
        caption: String,
        now: Instant,
    ) -> Result<u32, OverlayResponse> {
        let encoded = qr_payload_text(data);
        let qrcode = QrCode::with_error_correction_level(encoded.as_bytes(), EcLevel::M)
            .map_err(|_| OverlayResponse::internal_error("create_qrcode_window"))?;
        let width = qrcode.width();
        let colors = qrcode.to_colors();
        let mut matrix = Vec::with_capacity(width);
        for row in colors.chunks(width) {
            matrix.push(
                row.iter()
                    .map(|color| matches!(color, Color::Dark))
                    .collect::<Vec<bool>>(),
            );
        }

        let id = self.next_qrcode_id;
        self.next_qrcode_id += 1;
        self.qrcode_order += 1;
        let pix_per_mod = 6_i32;
        let qr_size = i32::try_from(width).unwrap_or(0) * pix_per_mod;
        self.qrcodes.insert(
            id,
            QrCodeEntry {
                matrix,
                qr_size,
                pix_per_mod,
                padding: 10,
                caption,
                order: self.qrcode_order,
                expires_at: now + duration,
            },
        );
        Ok(id)
    }

    fn close_window(&mut self, window_id: u32) -> bool {
        if self.countdowns.remove(&window_id).is_some() {
            return true;
        }
        if self.qrcodes.remove(&window_id).is_some() {
            return true;
        }
        let previous_len = self.rectangles.len();
        self.rectangles.retain(|entry| entry.id != window_id);
        previous_len != self.rectangles.len()
    }

    fn update_window(&mut self, window_id: u32, new_message: String) -> bool {
        let Some(countdown) = self.countdowns.get_mut(&window_id) else {
            return false;
        };
        countdown.message = new_message;
        true
    }

    fn is_break_active(&mut self, now: Instant) -> bool {
        match self.break_until {
            Some(deadline) if now < deadline => true,
            Some(_) => {
                self.break_until = None;
                false
            }
            None => false,
        }
    }
}

fn run_actor(receiver: Receiver<ActorMessage>, ui_bridge: UiBridge) {
    let mut state = OverlayState::default();
    let mut next_tick = Instant::now() + TICK_INTERVAL;

    loop {
        let now = Instant::now();
        let timeout = next_tick.saturating_duration_since(now);
        match receiver.recv_timeout(timeout) {
            Ok(ActorMessage::Execute { command, reply }) => {
                let (response, changed) = state.execute(command, Instant::now());
                if changed {
                    ui_bridge.replace_snapshot(state.snapshot());
                }
                let _ = reply.send(response);
            }
            Ok(ActorMessage::Shutdown) => break,
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => break,
        }

        let now = Instant::now();
        if now >= next_tick {
            if state.tick(now) {
                ui_bridge.replace_snapshot(state.snapshot());
            }
            next_tick = now + TICK_INTERVAL;
        }
    }
}

pub fn remaining_seconds(end_time: Instant, now: Instant) -> u64 {
    match end_time.checked_duration_since(now) {
        Some(duration) => duration.as_secs_f64().ceil() as u64,
        None => 0,
    }
}

pub fn elapsed_seconds(start_time: Instant, now: Instant) -> u64 {
    if now <= start_time {
        return 0;
    }
    let elapsed = now.duration_since(start_time).as_secs_f64().ceil() as u64;
    elapsed.saturating_sub(1)
}

fn duration_from_seconds(seconds: f64, field_name: &str) -> Result<Duration, OverlayResponse> {
    let normalized = validate_duration_seconds(seconds, field_name)?;
    Duration::try_from_secs_f64(normalized)
        .map_err(|_| OverlayResponse::error(format!("Invalid {field_name}")))
}

fn duration_ceil_seconds(duration: Duration) -> u64 {
    duration
        .as_secs()
        .saturating_add(u64::from(duration.subsec_nanos() > 0))
}

fn qr_payload_text(data: &Value) -> String {
    match data {
        Value::String(text) => text.clone(),
        Value::Object(_) => serde_json::to_string(data).unwrap_or_default(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use serde_json::json;

    use super::{OverlayState, elapsed_seconds, remaining_seconds};
    use crate::protocol::{OverlayResponse, ParsedCommand, WindowIdArg};

    #[test]
    fn countdown_math_matches_python_behavior() {
        let now = std::time::Instant::now();
        assert_eq!(remaining_seconds(now + Duration::from_millis(250), now), 1);
        assert_eq!(remaining_seconds(now + Duration::from_millis(1250), now), 2);
        assert_eq!(remaining_seconds(now - Duration::from_secs(1), now), 0);
    }

    #[test]
    fn elapsed_math_stays_zero_for_first_second() {
        let now = std::time::Instant::now();
        assert_eq!(elapsed_seconds(now, now + Duration::from_millis(100)), 0);
        assert_eq!(elapsed_seconds(now, now + Duration::from_millis(1100)), 1);
    }

    #[test]
    fn close_window_prefers_countdown_then_qr_then_highlight() {
        let now = std::time::Instant::now();
        let mut state = OverlayState::default();
        let _ = state.execute(
            ParsedCommand::CreateCountdown {
                message_text: "countdown".to_string(),
                countdown_seconds: 10.0,
            },
            now,
        );
        let _ = state.execute(
            ParsedCommand::CreateHighlight {
                rect: Some([0, 0, 10, 10]),
                timeout_seconds: 10.0,
            },
            now,
        );

        let (response, changed) = state.execute(
            ParsedCommand::CloseWindow {
                window_id: WindowIdArg {
                    provided: true,
                    numeric: Some(1),
                    display: "1".to_string(),
                },
            },
            now,
        );
        assert_eq!(
            response,
            OverlayResponse::success_message("Window 1 closed")
        );
        assert!(changed);
        assert!(!state.countdowns.contains_key(&1));
        assert_eq!(state.rectangles.len(), 1);
    }

    #[test]
    fn break_discards_and_does_not_replay() {
        let now = std::time::Instant::now();
        let mut state = OverlayState::default();
        let _ = state.execute(
            ParsedCommand::TakeBreak {
                duration_seconds: 5.0,
                duration_display: "5".to_string(),
            },
            now,
        );

        let (response, changed) = state.execute(
            ParsedCommand::CreateCountdown {
                message_text: "discard".to_string(),
                countdown_seconds: 5.0,
            },
            now + Duration::from_millis(100),
        );
        assert_eq!(
            response,
            OverlayResponse::ignored("break_active", "Command discarded during break")
        );
        assert!(!changed);
        assert!(state.countdowns.is_empty());

        let (response, changed) = state.execute(
            ParsedCommand::CreateCountdown {
                message_text: "keep".to_string(),
                countdown_seconds: 5.0,
            },
            now + Duration::from_secs(6),
        );
        assert_eq!(response, OverlayResponse::success_window(1));
        assert!(changed);
        assert_eq!(state.countdowns.len(), 1);
    }

    #[test]
    fn qrcode_object_data_round_trips_as_json() {
        let now = std::time::Instant::now();
        let mut state = OverlayState::default();
        let (response, changed) = state.execute(
            ParsedCommand::CreateQrCodeWindow {
                data: json!({"url":"https://example.com"}),
                duration_seconds: 5.0,
                caption: "Scan".to_string(),
            },
            now,
        );
        assert_eq!(response, OverlayResponse::success_window(1));
        assert!(changed);
        assert_eq!(state.qrcodes.len(), 1);
    }
}
