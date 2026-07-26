"""GeeTest V3 ``w`` parameter generation.

``w`` is an AES-CBC encrypted JSON payload concatenated with the RSA-encrypted
AES key, the ciphertext carried in GeeTest's own Base64 variant.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Dict, List, Sequence, Tuple

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

__all__ = ["click_w", "slide_w"]

_AES_KEY = b"1234567890123456"
_AES_IV = b"0000000000000000"
_RSA_MODULUS = int(
    "00C1E3934D1614465B33053E7F48EE4EC87B14B95EF88947713D25EECBFF7E74"
    "C7977D02DC1D9451F79DD5D1C10C29ACB6A9B4D6FB7D0A0279B6719E1772565F"
    "09AF627715919221AEF91899CAE08C0D686D748B20A3603BE2318CA6BC2B59706"
    "592A9219D0BF05C9F65023A21D2330807252AE0066D59CEEFA5F2748EA80BAB81",
    16,
)
_RSA_EXPONENT = 0x10001

# GeeTest's Base64 alphabet, with '.' as padding.
_BASE64_ALPHABET = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()"
# 每个掩码恰有 6 个置位，从 24 位输入中挑出一个输出字符的位。
_MASKS = (7274496, 9483264, 19220, 235)


def click_w(coords: Sequence[Tuple[float, float]], gt: str, challenge: str) -> str:
    """由点击坐标计算点选验证码的 ``w``。"""

    if not coords:
        raise ValueError("coords must not be empty")
    if not gt or not challenge:
        raise ValueError("gt and challenge must not be empty")

    pass_time = 1300 + time.time_ns() % 700
    now_ms = int(time.time() * 1000)
    payload = {
        "lang": "zh-cn",
        "passtime": pass_time,
        "a": _click_key(coords),
        "tt": "",
        "ep": _environment(now_ms),
        "h9s9": "1816378497",
        "rp": _rp(gt, challenge, pass_time),
    }
    return _encrypt_payload(payload)


def slide_w(
    distance: int,
    encrypted_track: str,
    gt: str,
    challenge: str,
    c: Sequence[int],
    s: str,
) -> str:
    """由滑动距离与轨迹计算滑动验证码的 ``w``。"""

    if distance <= 0:
        raise ValueError("distance must be positive")
    if not encrypted_track or not gt or not challenge:
        raise ValueError("encrypted_track, gt and challenge must not be empty")

    now_ns = time.time_ns()
    pass_time = 1500 + now_ns % 500
    now_ms = int(time.time() * 1000)
    payload = {
        "lang": "zh-cn",
        "userresponse": _user_response(distance, challenge),
        "passtime": pass_time,
        "imgload": 100 + now_ns % 100,
        "aa": _obfuscate_track(encrypted_track, bytes(c), s),
        "ep": _environment(now_ms),
        "rp": _rp(gt, challenge, pass_time),
    }
    return _encrypt_payload(payload)


def _rp(gt: str, challenge: str, pass_time: int) -> str:
    prefix = challenge[:-2] if len(challenge) > 2 else challenge
    return hashlib.md5("{}{}{}".format(gt, prefix, pass_time).encode()).hexdigest()


def _click_key(coords: Sequence[Tuple[float, float]]) -> str:
    def scale(value: float) -> int:
        # 半数向远离零舍入；Python 内置 round 用的是银行家舍入，此处不适用。
        scaled = value / 333.375 * 10000
        return int(math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5))

    return ",".join("{}_{}".format(scale(x), scale(y)) for x, y in coords)


def _environment(now_ms: int) -> Dict[str, object]:
    return {
        "v": "9.1.8-bfget5",
        "$_E_": False,
        "me": True,
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
            "t": now_ms - 21, "u": now_ms - 21,
        },
        "dnf": "dnf",
        "by": 0,
    }


def _encrypt_payload(payload: Dict[str, object]) -> str:
    # 键序须与浏览器实际发出的顺序一致，故不排序；分隔符也不留空格。
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()

    padding_length = 16 - len(body) % 16
    padded = body + bytes([padding_length]) * padding_length
    encryptor = Cipher(algorithms.AES(_AES_KEY), modes.CBC(_AES_IV)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    public_key = rsa.RSAPublicNumbers(_RSA_EXPONENT, _RSA_MODULUS).public_key()
    encrypted_key = public_key.encrypt(_AES_KEY, padding.PKCS1v15())

    return _geetest_base64(ciphertext) + encrypted_key.hex()


def _geetest_base64(data: bytes) -> str:
    def pick(base: int, mask: int) -> int:
        result = 0
        for bit in range(23, -1, -1):
            if (mask >> bit) & 1:
                result = (result << 1) | ((base >> bit) & 1)
        return result

    out = bytearray()
    for offset in range(0, len(data), 3):
        chunk = data[offset : offset + 3]
        base = chunk[0] << 16
        if len(chunk) > 1:
            base |= chunk[1] << 8
        if len(chunk) > 2:
            base |= chunk[2]
        out.append(_BASE64_ALPHABET[pick(base, _MASKS[0])])
        out.append(_BASE64_ALPHABET[pick(base, _MASKS[1])])
        out.append(_BASE64_ALPHABET[pick(base, _MASKS[2])] if len(chunk) >= 2 else ord("."))
        out.append(_BASE64_ALPHABET[pick(base, _MASKS[3])] if len(chunk) == 3 else ord("."))
    return out.decode("ascii")


def _obfuscate_track(track: str, c: bytes, s: str) -> str:
    """按服务端下发的 ``c``/``s`` 向轨迹中插入字节。"""

    if len(c) < 5 or not s or not track:
        return track

    # 插入偏移量按【原始】长度取模，可能落在多字节字符中间，故在字节缓冲上操作。
    original_length = len(track.encode())
    out = bytearray(track.encode())
    for index in range(0, len(s) - 1, 2):
        try:
            value = int(s[index : index + 2], 16)
        except ValueError:
            continue
        position = (c[0] * value * value + c[2] * value + c[4]) % original_length
        out[position:position] = chr(value).encode()
    # 按字节插入可能切断多字节序列，非法部分按惯例替换为 U+FFFD。
    return out.decode("utf-8", "replace")


def _user_response(distance: int, challenge: str) -> str:
    if len(challenge) < 2:
        return ""

    def base36(char: str) -> int:
        return int(char, 36)

    remaining = distance + 36 * base36(challenge[-2]) + base36(challenge[-1])

    buckets: List[List[str]] = [[], [], [], [], []]
    seen = set()
    index = 0
    for char in challenge[:-2]:
        if char not in seen:
            seen.add(char)
            buckets[index].append(char)
            index = (index + 1) % len(buckets)

    weights = (1, 2, 5, 10, 50)
    weight_index = len(weights) - 1
    out: List[str] = []
    while remaining > 0:
        if remaining >= weights[weight_index] and buckets[weight_index]:
            out.append(buckets[weight_index][0])
            remaining -= weights[weight_index]
        elif weight_index == 0:
            break
        else:
            weight_index -= 1
    return "".join(out)
