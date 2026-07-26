//! 极验 V3 `w` 参数生成（RSA + AES-CBC + 自定义 Base64）。
//!
//! 忠实移植自本项目 `gtlv-go/pkg/crypto`；不依赖上游网络实现。

use std::collections::HashSet;
use std::time::{SystemTime, UNIX_EPOCH};

use aes::Aes128;
use cbc::cipher::{block_padding::Pkcs7, BlockEncryptMut, KeyIvInit};
use rand::rngs::OsRng;
use rsa::{Pkcs1v15Encrypt, RsaPublicKey};
use serde_json::{json, Value};

type Aes128CbcEncryptor = cbc::Encryptor<Aes128>;

const AES_KEY: &[u8; 16] = b"1234567890123456";
const AES_IV: &[u8; 16] = b"0000000000000000";
const RSA_N_HEX: &str = concat!(
    "00C1E3934D1614465B33053E7F48EE4EC87B14B95EF88947713D25EECBFF7E74",
    "C7977D02DC1D9451F79DD5D1C10C29ACB6A9B4D6FB7D0A0279B6719E1772565F",
    "09AF627715919221AEF91899CAE08C0D686D748B20A3603BE2318CA6BC2B59706",
    "592A9219D0BF05C9F65023A21D2330807252AE0066D59CEEFA5F2748EA80BAB81"
);
const RSA_E_HEX: &str = "010001";

pub fn click_w(coords: &[(f64, f64)], gt: &str, challenge: &str) -> Result<String, String> {
    let key = generate_click_key(coords);
    let now_nanos = unix_nanos();
    let pass_time = 1300 + (now_nanos % 700) as i64;
    let now_ms = unix_millis();
    let rp = md5_hex(format!("{gt}{}{pass_time}", challenge_prefix(challenge)).as_bytes());
    let payload = json!({
        "lang": "zh-cn",
        "passtime": pass_time,
        "a": key,
        "tt": "",
        "ep": common_ep(now_ms),
        "h9s9": "1816378497",
        "rp": rp,
    });
    encrypt_payload(&payload)
}

pub fn slide_w(
    distance: i32,
    encrypted_track: &str,
    gt: &str,
    challenge: &str,
    c: &[u8],
    s: &str,
) -> Result<String, String> {
    let now_nanos = unix_nanos();
    let pass_time = 1500 + (now_nanos % 500) as i64;
    let now_ms = unix_millis();
    let aa = slide_final_encrypt(encrypted_track, c, s);
    let user_response = user_response(distance, challenge);
    let rp = md5_hex(format!("{gt}{}{pass_time}", challenge_prefix(challenge)).as_bytes());
    let payload = json!({
        "lang": "zh-cn",
        "userresponse": user_response,
        "passtime": pass_time,
        "imgload": 100 + (now_nanos % 100) as i64,
        "aa": aa,
        "ep": common_ep(now_ms),
        "rp": rp,
    });
    encrypt_payload(&payload)
}

fn unix_nanos() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
}

fn unix_millis() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

fn challenge_prefix(challenge: &str) -> &str {
    challenge
        .char_indices()
        .rev()
        .nth(1)
        .map_or(challenge, |(index, _)| &challenge[..index])
}

fn common_ep(now_ms: i64) -> Value {
    json!({
        "v": "9.1.8-bfget5",
        "$_E_": false,
        "me": true,
        "ven": "Google Inc. (Intel)",
        "ren": "ANGLE (Intel, Intel(R) HD Graphics 520 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "fp": ["move", 483, 149, now_ms - 300, "pointermove"],
        "lp": ["up", 657, 100, now_ms, "pointerup"],
        "em": {"ph": 0, "cp": 0, "ek": "11", "wd": 1, "nt": 0, "si": 0, "sc": 0},
        "tm": {
            "a": now_ms - 500, "b": now_ms - 308, "c": now_ms - 308,
            "d": 0, "e": 0, "f": now_ms - 496, "g": now_ms - 474,
            "h": now_ms - 474, "i": now_ms - 474, "j": now_ms - 414,
            "k": now_ms - 447, "l": now_ms - 414, "m": now_ms - 317,
            "n": now_ms - 313, "o": now_ms - 305, "p": now_ms - 27,
            "q": now_ms - 27, "r": now_ms - 22, "s": now_ms - 21,
            "t": now_ms - 21, "u": now_ms - 21
        },
        "dnf": "dnf",
        "by": 0
    })
}

fn generate_click_key(coords: &[(f64, f64)]) -> String {
    coords
        .iter()
        .map(|&(x, y)| {
            let scaled_x = (x / 333.375 * 10_000.0).round() as i64;
            let scaled_y = (y / 333.375 * 10_000.0).round() as i64;
            format!("{scaled_x}_{scaled_y}")
        })
        .collect::<Vec<_>>()
        .join(",")
}

fn encrypt_payload(payload: &Value) -> Result<String, String> {
    let json = serde_json::to_vec(payload).map_err(|e| format!("serialize payload: {e}"))?;
    let ciphertext = Aes128CbcEncryptor::new(AES_KEY.into(), AES_IV.into())
        .encrypt_padded_vec_mut::<Pkcs7>(&json);
    let encrypted_key = rsa_encrypt(AES_KEY)?;
    Ok(format!("{}{}", custom_base64(&ciphertext), encrypted_key))
}

fn rsa_encrypt(data: &[u8]) -> Result<String, String> {
    let modulus = hex::decode(RSA_N_HEX).map_err(|e| format!("decode RSA modulus: {e}"))?;
    let exponent = hex::decode(RSA_E_HEX).map_err(|e| format!("decode RSA exponent: {e}"))?;
    let public_key = RsaPublicKey::new(
        rsa::BigUint::from_bytes_be(&modulus),
        rsa::BigUint::from_bytes_be(&exponent),
    )
    .map_err(|e| format!("construct RSA key: {e}"))?;
    let encrypted = public_key
        .encrypt(&mut OsRng, Pkcs1v15Encrypt, data)
        .map_err(|e| format!("RSA encrypt: {e}"))?;
    Ok(hex::encode(encrypted))
}

fn md5_hex(data: &[u8]) -> String {
    format!("{:x}", md5::compute(data))
}

const BASE64_TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()";
const MASKS: [u32; 4] = [7_274_496, 9_483_264, 19_220, 235];

fn custom_base64(data: &[u8]) -> String {
    fn get_by_mask(base: u32, mask: u32) -> usize {
        let mut result = 0_u32;
        for bit in (0..24).rev() {
            if (mask >> bit) & 1 == 1 {
                result = (result << 1) | ((base >> bit) & 1);
            }
        }
        result as usize
    }

    let mut output = Vec::with_capacity(data.len() * 4 / 3 + 4);
    for chunk in data.chunks(3) {
        let base = (u32::from(chunk[0]) << 16)
            | (chunk.get(1).copied().map(u32::from).unwrap_or(0) << 8)
            | chunk.get(2).copied().map(u32::from).unwrap_or(0);
        output.push(BASE64_TABLE[get_by_mask(base, MASKS[0])]);
        output.push(BASE64_TABLE[get_by_mask(base, MASKS[1])]);
        if chunk.len() >= 2 {
            output.push(BASE64_TABLE[get_by_mask(base, MASKS[2])]);
        } else {
            output.push(b'.');
        }
        if chunk.len() == 3 {
            output.push(BASE64_TABLE[get_by_mask(base, MASKS[3])]);
        } else {
            output.push(b'.');
        }
    }
    String::from_utf8(output).expect("custom base64 table is ASCII")
}

fn slide_final_encrypt(track: &str, c: &[u8], s: &str) -> String {
    if c.len() < 5 || s.is_empty() || track.is_empty() {
        return track.to_owned();
    }
    let original_len = track.len();
    // 插入按【字节】位置进行：偏移量由原始长度取模得出，可能落在多字节字符中间，
    // 按字符插入会在那里 panic。
    let mut output = track.as_bytes().to_vec();
    for pair in s.as_bytes().chunks_exact(2) {
        let Ok(pair) = std::str::from_utf8(pair) else {
            continue;
        };
        let Ok(value) = u8::from_str_radix(pair, 16) else {
            continue;
        };
        let value_u64 = u64::from(value);
        let position = (u64::from(c[0]) * value_u64 * value_u64
            + u64::from(c[2]) * value_u64
            + u64::from(c[4]))
            % original_len as u64;
        // 插入的是该字节值对应码点的 UTF-8 编码，≥0x80 时为 2 字节。
        let mut encoded = [0_u8; 4];
        let encoded = char::from(value).encode_utf8(&mut encoded).as_bytes();
        output.splice(
            position as usize..position as usize,
            encoded.iter().copied(),
        );
    }
    // 按字节插入可能切断多字节序列，非法部分按惯例替换为 U+FFFD。
    String::from_utf8_lossy(&output).into_owned()
}

fn user_response(distance: i32, challenge: &str) -> String {
    let bytes = challenge.as_bytes();
    if bytes.len() < 2 {
        return String::new();
    }
    fn base36(value: u8) -> i32 {
        if value > b'9' {
            i32::from(value.to_ascii_lowercase() - b'a') + 10
        } else {
            i32::from(value - b'0')
        }
    }
    let suffix = &bytes[bytes.len() - 2..];
    let mut remaining = distance + 36 * base36(suffix[0]) + base36(suffix[1]);

    let mut buckets = [Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new()];
    let mut seen = HashSet::new();
    let mut bucket = 0;
    for &value in &bytes[..bytes.len() - 2] {
        if seen.insert(value) {
            buckets[bucket].push(value);
            bucket = (bucket + 1) % buckets.len();
        }
    }

    let weights = [1, 2, 5, 10, 50];
    let mut weight_index = weights.len() - 1;
    let mut output = Vec::new();
    while remaining > 0 {
        if remaining >= weights[weight_index] && !buckets[weight_index].is_empty() {
            output.push(buckets[weight_index][0]);
            remaining -= weights[weight_index];
        } else if weight_index == 0 {
            break;
        } else {
            weight_index -= 1;
        }
    }
    String::from_utf8(output).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scales_click_coordinates_like_go_reference() {
        assert_eq!(
            generate_click_key(&[(333.375, 0.0), (166.6875, 333.375)]),
            "10000_0,5000_10000"
        );
    }

    #[test]
    fn custom_base64_padding_and_zero_block() {
        assert_eq!(custom_base64(&[0, 0, 0]), "AAAA");
        assert_eq!(custom_base64(&[0]), "AA..");
        assert_eq!(custom_base64(&[0, 0]), "AAA.");
    }

    #[test]
    fn slide_encrypt_survives_high_bytes_landing_mid_character() {
        // ≥0x80 的值编码成 2 字节 UTF-8；后续插入位置可能落在其中间。
        // 插入位置按原始长度取模，可能落在多字节字符中间；按字符插入会在此 panic。
        let got = slide_final_encrypt("aaaaaaaaaaaaaaaaaaaa", &[1, 2, 3, 4, 5], "80ff017f90a0");
        assert!(got.len() > 20);
    }

    #[test]
    fn generated_w_has_encrypted_payload_and_rsa_suffix() {
        let click = click_w(&[(120.0, 80.0)], "gt", "challengezz").unwrap();
        let slide = slide_w(120, "a!!b!!c", "gt", "challengezz", &[1, 2, 3, 4, 5], "0a").unwrap();
        for value in [click, slide] {
            assert!(value.len() > 256);
            assert!(value[value.len() - 256..]
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit()));
        }
    }
}
