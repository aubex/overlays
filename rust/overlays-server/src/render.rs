use crate::state::{CountdownSnapshot, CountdownVisualState, OverlaySnapshot};

pub const BOX_W: i32 = 300;
pub const BOX_H: i32 = 80;
pub const GAP: i32 = 10;
pub const TOP: i32 = 20;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TextSize {
    pub width: i32,
    pub height: i32,
}

pub fn get_countdown_position(index: usize, full: (i32, i32, i32, i32)) -> (i32, i32, i32, i32) {
    let left = (full.2 - BOX_W) / 2;
    let top = TOP + (index as i32 * (BOX_H + GAP));
    let right = left + BOX_W;
    let bottom = top + BOX_H;
    (left, top, right, bottom)
}

pub fn get_qrcode_position(
    index: usize,
    total: i32,
    box_gap: i32,
    top_start: i32,
    full: (i32, i32, i32, i32),
) -> (i32, i32, i32, i32) {
    let left = (full.2 - total) / 2;
    let top = top_start + (index as i32 * (total + box_gap));
    let right = left + total;
    let bottom = top + total;
    (left, top, right, bottom)
}

pub fn countdown_lines(countdown: &CountdownSnapshot) -> Vec<String> {
    let mut lines = vec![countdown.message.clone()];
    match countdown.visual {
        CountdownVisualState::Countdown { remaining } => {
            lines.push(format!("Closing in {remaining} s"));
        }
        CountdownVisualState::Elapsed { elapsed } => {
            lines.push(format!("Elapsed time: {elapsed} seconds"));
        }
    }
    lines
}

pub fn countdown_box_rect(
    position: (i32, i32, i32, i32),
    sizes: &[TextSize],
    padding: (i32, i32),
) -> (i32, i32, i32, i32) {
    let (left, top, right, _) = position;
    let initial_width = right - left;
    let (pad_x, pad_y) = padding;
    let text_width = sizes.iter().map(|size| size.width).max().unwrap_or(0);
    let text_height: i32 = sizes.iter().map(|size| size.height).sum();
    let initial_center_x = left + (initial_width / 2);
    let content_half_width = initial_width.max(text_width) / 2;
    let final_left = initial_center_x - content_half_width - pad_x;
    let final_right = initial_center_x + content_half_width + pad_x;
    let final_top = top - pad_y;
    let final_bottom = final_top + text_height + (2 * pad_y);
    (final_left, final_top, final_right, final_bottom)
}

pub fn qr_top_start(snapshot: &OverlaySnapshot) -> i32 {
    20 + (snapshot.countdowns.len() as i32 * (80 + 10))
}

pub fn qrcode_background_rect(
    position: (i32, i32, i32, i32),
    caption_size: Option<TextSize>,
) -> (i32, i32, i32, i32) {
    let (left, top, right, bottom) = position;
    let qr_width = right - left;
    let (caption_width, caption_height) = caption_size
        .map(|size| (size.width, size.height))
        .unwrap_or((0, 0));
    let extra = (caption_width - qr_width).max(0);
    let left_expansion = extra / 2;
    let right_expansion = extra - left_expansion;
    let h_margin = 5;
    let v_margin = 5;
    let bg_bottom = if caption_height > 0 {
        bottom + caption_height + h_margin
    } else {
        bottom
    };
    (
        left - left_expansion - h_margin,
        top - v_margin,
        right + right_expansion + h_margin,
        bg_bottom,
    )
}

pub fn qrcode_caption_rect(
    position: (i32, i32, i32, i32),
    caption_size: TextSize,
    background_rect: (i32, i32, i32, i32),
) -> (i32, i32, i32, i32) {
    let (_, _, _, bottom) = position;
    let (bg_left, _, bg_right, _) = background_rect;
    let caption_top = bottom + 2;
    (
        bg_left,
        caption_top,
        bg_right,
        caption_top + caption_size.height,
    )
}

#[cfg(test)]
mod tests {
    use super::{
        BOX_H, BOX_W, GAP, TOP, TextSize, countdown_box_rect, countdown_lines,
        get_countdown_position, get_qrcode_position, qrcode_background_rect,
    };
    use crate::state::{CountdownSnapshot, CountdownVisualState};

    #[test]
    fn countdown_position_matches_python_math() {
        let rect = get_countdown_position(2, (0, 0, 1000, 800));
        let expected_left = (1000 - BOX_W) / 2;
        let expected_top = TOP + 2 * (BOX_H + GAP);
        assert_eq!(
            rect,
            (
                expected_left,
                expected_top,
                expected_left + BOX_W,
                expected_top + BOX_H,
            )
        );
    }

    #[test]
    fn qrcode_position_matches_python_math() {
        let rect = get_qrcode_position(1, 120, 10, 200, (0, 0, 1000, 800));
        assert_eq!(rect, ((1000 - 120) / 2, 330, ((1000 - 120) / 2) + 120, 450));
    }

    #[test]
    fn countdown_box_expands_around_center() {
        let rect = countdown_box_rect(
            (10, 20, 110, 70),
            &[
                TextSize {
                    width: 140,
                    height: 10,
                },
                TextSize {
                    width: 80,
                    height: 20,
                },
            ],
            (5, 5),
        );
        assert_eq!(rect, (-15, 15, 135, 55));
    }

    #[test]
    fn countdown_lines_match_visual_state() {
        let countdown = CountdownSnapshot {
            id: 1,
            message: "Wait".to_string(),
            order: 1,
            visual: CountdownVisualState::Countdown { remaining: 5 },
        };
        assert_eq!(
            countdown_lines(&countdown),
            vec!["Wait".to_string(), "Closing in 5 s".to_string()]
        );
    }

    #[test]
    fn qrcode_background_grows_for_caption() {
        let rect = qrcode_background_rect(
            (0, 0, 6, 6),
            Some(TextSize {
                width: 16,
                height: 10,
            }),
        );
        assert_eq!(rect, (-10, -5, 16, 21));
    }
}
