//! 滑动验证码的纯本地求解：背景还原、缺口识别、轨迹生成与编码。
//!
//! 忠实移植自本项目 `gtlv-go/pkg/solver/classic`，不触网。

use image::{DynamicImage, RgbaImage};
use rand::Rng;

const OFFSETS: [u32; 52] = [
    39, 38, 48, 49, 41, 40, 46, 47, 35, 34, 50, 51, 33, 32, 28, 29, 27, 26, 36, 37, 31, 30, 44, 45,
    43, 42, 12, 13, 23, 22, 14, 15, 21, 20, 8, 9, 25, 24, 6, 7, 3, 2, 0, 1, 11, 10, 4, 5, 19, 18,
    16, 17,
];

pub struct Result {
    pub distance: i32,
    pub encrypted_track: String,
}

pub fn solve(bg: &[u8], fullbg: &[u8]) -> std::result::Result<Result, String> {
    let bg = image::load_from_memory(bg).map_err(|e| format!("decode bg: {e}"))?;
    let fullbg = image::load_from_memory(fullbg).map_err(|e| format!("decode fullbg: {e}"))?;
    let restored_bg = restore(&bg)?;
    let restored_fullbg = restore(&fullbg)?;
    let distance = identify_gap(&restored_bg, &restored_fullbg);
    if distance <= 0 {
        return Err(format!("gap not found (distance={distance})"));
    }
    let track = generate_track(distance);
    Ok(Result {
        distance,
        encrypted_track: encrypt_track(&track),
    })
}

fn restore(image: &DynamicImage) -> std::result::Result<RgbaImage, String> {
    let source = image.to_rgba8();
    if source.width() < 310 || source.height() < 160 {
        return Err(format!(
            "background too small: {}x{} (need at least 310x160)",
            source.width(),
            source.height()
        ));
    }

    let mut restored = RgbaImage::new(260, 160);
    for (index, offset) in OFFSETS.iter().copied().enumerate() {
        let source_x = (offset % 26) * 12;
        let source_y = if offset > 25 { 80 } else { 0 };
        let destination_x = (index as u32 % 26) * 10;
        let destination_y = if index > 25 { 80 } else { 0 };
        for y in 0..80 {
            for x in 0..10 {
                restored.put_pixel(
                    destination_x + x,
                    destination_y + y,
                    *source.get_pixel(source_x + x, source_y + y),
                );
            }
        }
    }
    Ok(restored)
}

fn identify_gap(bg: &RgbaImage, fullbg: &RgbaImage) -> i32 {
    let width = bg.width().min(fullbg.width());
    let height = bg.height().min(fullbg.height());
    if width <= 80 || height == 0 {
        return 0;
    }

    let mut best_x = 0;
    let mut max_diff = 0_u64;
    for x in 40..width - 40 {
        let mut total_diff = 0_u64;
        for y in 0..height {
            let left = bg.get_pixel(x, y).0;
            let right = fullbg.get_pixel(x, y).0;
            let diff = left[0].abs_diff(right[0]) as u64
                + left[1].abs_diff(right[1]) as u64
                + left[2].abs_diff(right[2]) as u64;
            if diff > 50 {
                total_diff += diff;
            }
        }
        if total_diff > max_diff {
            max_diff = total_diff;
            best_x = x as i32;
        }
    }
    best_x
}

type TrackPoint = [i32; 3];

fn generate_track(distance: i32) -> Vec<TrackPoint> {
    if distance <= 0 {
        return vec![[0, 0, 0]];
    }

    let mut rng = rand::thread_rng();
    let mut track = vec![
        [rng.gen_range(-50..=-10), rng.gen_range(-50..=-10), 0],
        [0, 0, 0],
    ];
    let count = 30 + distance / 2;
    let mut time = rng.gen_range(50..=100);
    let mut last_x = 0;

    for index in 0..count {
        let progress = index as f64 / count as f64;
        let x = ((1.0 - 2_f64.powf(-10.0 * progress)) * distance as f64).round() as i32;
        time += rng.gen_range(10..=20);
        if x == last_x {
            continue;
        }
        track.push([x, 0, time]);
        last_x = x;
    }
    if let Some(last) = track.last().copied() {
        track.push(last);
    }
    track
}

fn encrypt_track(track: &[TrackPoint]) -> String {
    if track.len() < 2 {
        return String::new();
    }

    #[derive(Clone, Copy)]
    struct Step {
        dx: i32,
        dy: i32,
        dt: i32,
    }

    let mut steps = Vec::new();
    let mut accumulated_dt = 0;
    for pair in track.windows(2) {
        let dx = pair[1][0] - pair[0][0];
        let dy = pair[1][1] - pair[0][1];
        let dt = pair[1][2] - pair[0][2];
        if dx == 0 && dy == 0 && dt == 0 {
            continue;
        }
        if dx == 0 && dy == 0 {
            accumulated_dt += dt;
        } else {
            steps.push(Step {
                dx,
                dy,
                dt: dt + accumulated_dt,
            });
            accumulated_dt = 0;
        }
    }
    if accumulated_dt != 0 {
        if let Some(last) = steps.last().copied() {
            steps.push(Step {
                dx: last.dx,
                dy: last.dy,
                dt: accumulated_dt,
            });
        }
    }

    const CHARSET: &[u8] = b"()*,-./0123456789:?@ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqr";
    fn encode_value(value: i32) -> String {
        let absolute = value.unsigned_abs() as usize;
        let mut quotient = absolute / CHARSET.len();
        if quotient >= CHARSET.len() {
            quotient = CHARSET.len() - 1;
        }
        let mut output = String::new();
        if value < 0 {
            output.push('!');
        }
        if quotient > 0 {
            output.push('$');
            output.push(CHARSET[quotient] as char);
        }
        output.push(CHARSET[absolute % CHARSET.len()] as char);
        output
    }

    const PAIRS: &[(i32, i32, char)] = &[
        (1, 0, 's'),
        (2, 0, 't'),
        (1, -1, 'u'),
        (1, 1, 'v'),
        (0, 1, 'w'),
        (0, -1, 'x'),
        (3, 0, 'y'),
        (2, -1, 'z'),
        (2, 1, '~'),
    ];

    let mut horizontal = String::new();
    let mut vertical = String::new();
    let mut timing = String::new();
    for step in steps {
        if let Some((_, _, encoded)) = PAIRS
            .iter()
            .find(|(dx, dy, _)| step.dx == *dx && step.dy == *dy)
        {
            vertical.push(*encoded);
        } else {
            horizontal.push_str(&encode_value(step.dx));
            vertical.push_str(&encode_value(step.dy));
        }
        timing.push_str(&encode_value(step.dt));
    }
    format!("{horizontal}!!{vertical}!!{timing}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn track_is_monotonic_and_has_expected_encoding_shape() {
        let track = generate_track(120);
        assert!(track.len() >= 3);
        assert_eq!(track[1], [0, 0, 0]);
        for pair in track[1..].windows(2) {
            assert!(pair[1][0] >= pair[0][0]);
            assert_eq!(pair[1][1], 0);
            assert!(pair[1][2] >= pair[0][2]);
        }
        assert!(track.iter().map(|point| point[0]).max().unwrap() >= 108);
        assert_eq!(encrypt_track(&track).matches("!!").count(), 2);
    }

    #[test]
    fn identifies_synthetic_gap() {
        let full = RgbaImage::from_pixel(260, 160, image::Rgba([200, 200, 200, 255]));
        let mut bg = full.clone();
        for y in 0..160 {
            for x in 130..138 {
                bg.put_pixel(x, y, image::Rgba([10, 10, 10, 255]));
            }
        }
        assert!((126..=134).contains(&identify_gap(&bg, &full)));
    }

    #[test]
    fn rejects_bad_image() {
        assert!(solve(b"not an image", b"also not an image").is_err());
    }
}
