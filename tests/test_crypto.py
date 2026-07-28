import json
import re
import unittest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from gtlv.crypto import (
    _click_key,
    _gt_base64,
    _obfuscate_track,
    _user_response,
    click_w,
    slide_w,
)

_ALPHABET = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()"
_MASKS = (7274496, 9483264, 19220, 235)


def _decrypt(w):
    """还原 w 的明文载荷，用于校验结构与键序。"""

    body = w[:-256]
    out = bytearray()
    for offset in range(0, len(body), 4):
        group = body[offset : offset + 4]
        values = [_ALPHABET.index(ord(c)) if c != "." else 0 for c in group]
        base = 0
        for value, mask in zip(values, _MASKS):
            bits = [b for b in range(23, -1, -1) if (mask >> b) & 1]
            for i, bit in enumerate(bits):
                if (value >> (len(bits) - 1 - i)) & 1:
                    base |= 1 << bit
        out.append((base >> 16) & 0xFF)
        if group[2] != ".":
            out.append((base >> 8) & 0xFF)
        if group[3] != ".":
            out.append(base & 0xFF)
    decryptor = Cipher(
        algorithms.AES(b"1234567890123456"), modes.CBC(b"0000000000000000")
    ).decryptor()
    plain = decryptor.update(bytes(out)) + decryptor.finalize()
    return plain[: -plain[-1]].decode()


class CryptoTests(unittest.TestCase):
    def test_click_key_scales_coordinates(self):
        self.assertEqual(_click_key([(333.375, 0.0), (166.6875, 333.375)]), "10000_0,5000_10000")

    def test_gt_base64_padding(self):
        self.assertEqual(_gt_base64(b"\0\0\0"), "AAAA")
        self.assertEqual(_gt_base64(b"\0"), "AA..")
        self.assertEqual(_gt_base64(b"\0\0"), "AAA.")

    def test_click_payload_key_order_matches_the_browser(self):
        # 键序参与指纹，必须保持这个顺序而非字母序。
        payload = _decrypt(click_w([(120.0, 80.0)], "gt", "0123456789abcdef"))
        self.assertEqual(
            re.findall(r'"([a-zA-Z_$0-9]+)":', payload)[:7],
            ["lang", "passtime", "a", "tt", "ep", "v", "$_E_"],
        )
        self.assertEqual(json.loads(payload)["lang"], "zh-cn")

    def test_w_carries_a_256_hex_rsa_suffix(self):
        for value in (
            click_w([(120.0, 80.0)], "gt", "challengezz"),
            slide_w(120, "a!!b!!c", "gt", "challengezz", [1, 2, 3, 4, 5], "0a"),
        ):
            self.assertGreater(len(value), 256)
            self.assertTrue(all(c in "0123456789abcdef" for c in value[-256:]))

    def test_track_obfuscation_survives_high_bytes(self):
        # ≥0x80 的值编码为 2 字节，插入偏移可能落在字符中间；按字节处理才不会失败。
        self.assertTrue(_obfuscate_track("a" * 20, bytes([1, 2, 3, 4, 5]), "80ff017f90a0"))

    def test_user_response_is_deterministic(self):
        self.assertEqual(
            _user_response(120, "0123456789abcdef0123456789abcdef"),
            _user_response(120, "0123456789abcdef0123456789abcdef"),
        )

    def test_rejects_empty_arguments(self):
        with self.assertRaises(ValueError):
            click_w([], "gt", "challenge")
        with self.assertRaises(ValueError):
            slide_w(0, "a!!b!!c", "gt", "challenge", [1, 2, 3, 4, 5], "0a")


if __name__ == "__main__":
    unittest.main()
