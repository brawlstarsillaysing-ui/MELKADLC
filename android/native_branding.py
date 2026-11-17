"""Pinned branding bitmap/strings and isolated adapters for two existing UI callbacks.

Feature instructions, relocations and exports are retained. The existing branding
CRC is updated; no integrity comparison is disabled. Only visible link labels are filtered.
"""

import base64
import hashlib
import json
import struct
import zlib
from pathlib import Path

ORIGINAL_MODULE_SHA = "bb56f9a9dacb5470780e992121944cc7b9de7972759bc09b3da5e8952ac09641"
BRANDING_OFFSET = 0x75A5C28
BRANDING_SIZE = 65566
CRC_LOW_OFFSET = 0x75BA44C
CRC_HIGH_OFFSET = 0x75BA450


def mask(i):
    return (i * 73 + (i >> 8) * 19 + 109) & 255


def patch_module(original):
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_MODULE_SHA, "Unknown native build"
    updated = bytearray(original)
    # Two fixed C-string slots consumed by the existing branding hook; retain offsets and capacities.
    strings = [(0, b"crack_komarq\0", b"MelkaDLC\0"), (13, b"tg:@crack_komarq\0", b"MelkaDLC\0")]
    for start, before, after in strings:
        plain = bytes(original[BRANDING_OFFSET + start + i] ^ mask(start + i) for i in range(len(before)))
        assert plain == before, "Unexpected branding data"
        assert len(after) <= len(before), "Brand exceeds fixed slot"
        for i, value in enumerate(after.ljust(len(before), b"\0")):
            updated[BRANDING_OFFSET + start + i] = value ^ mask(start + i)
    ui = json.loads((Path(__file__).parent / "native-ui/ui-patch.json").read_text())
    rgba = zlib.decompress(base64.b64decode(ui["rgba_zlib"]))
    assert len(rgba) == 65536 and hashlib.sha256(rgba).hexdigest() == ui["rgba_sha256"]
    assert rgba[-14:] == bytes(14)
    for i, value in enumerate(rgba, 30):
        updated[BRANDING_OFFSET + i] = value ^ mask(i)
    code = zlib.decompress(base64.b64decode(ui["code_zlib"]))
    assert hashlib.sha256(code).hexdigest() == ui["code_sha256"]
    start = ui["file_offset"]
    assert start == 0x75BD000 and start + len(code) < 0x75C0000
    assert not any(original[start : start + len(code)]), "UI code padding is not empty"
    updated[start : start + len(code)] = code
    # Redirect only the two pre-existing branding/image callbacks, preserving all feature text/code.
    for offset, vaddr, target in [
        (0x75BA834, 0x7A7E834, ui["full_entry"]),
        (0x75BAA98, 0x7A7EA98, ui["plain_entry"]),
    ]:
        assert struct.unpack_from("<I", original, offset)[0] == 0xD101C3FF
        delta = target - vaddr
        assert delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27)
        struct.pack_into("<I", updated, offset, 0x14000000 | ((delta // 4) & 0x03FFFFFF))
    phoff = struct.unpack_from("<Q", original, 32)[0]
    stride = struct.unpack_from("<H", original, 54)[0]
    assert stride == 56
    rx = phoff + 9 * stride
    rw = phoff + 11 * stride
    assert struct.unpack_from("<QQ", original, rx + 8) == (0x75A4000, 0x7A68000)
    assert struct.unpack_from("<II", original, rx) == (1, 5)
    assert struct.unpack_from("<QQ", original, rx + 32) == (0x18B68, 0x18B68)
    assert struct.unpack_from("<Q", original, rw + 16)[0] == 0x7A88000
    assert struct.unpack_from("<II", original, rw) == (1, 6)
    assert struct.unpack_from("<Q", original, rw + 40)[0] == 0x11CF9
    new_size = start + len(code) - 0x75A4000
    struct.pack_into("<QQ", updated, rx + 32, new_size, new_size)
    struct.pack_into("<Q", updated, rw + 40, 0x12100)
    expected = zlib.crc32(updated[BRANDING_OFFSET : BRANDING_OFFSET + BRANDING_SIZE]) ^ 0xFFFFFFFF
    # ARM64 MOVZ/MOVK only: change the embedded release CRC, retaining opcode, register and shift.
    for offset, shift, previous in [(CRC_LOW_OFFSET, 0, 0x98F9), (CRC_HIGH_OFFSET, 16, 0x0738)]:
        word = struct.unpack_from("<I", original, offset)[0]
        assert (word >> 5) & 0xFFFF == previous, "Unexpected CRC constant"
        word = (word & ~(0xFFFF << 5)) | (((expected >> shift) & 0xFFFF) << 5)
        struct.pack_into("<I", updated, offset, word)
    # Prove that the entire remaining binary, including all feature code, is byte-identical.
    allowed = sorted(
        [
            (BRANDING_OFFSET, BRANDING_SIZE),
            (CRC_LOW_OFFSET, 8),
            (0x75BA834, 4),
            (0x75BAA98, 4),
            (start, len(code)),
            (rx + 32, 16),
            (rw + 40, 8),
        ]
    )
    cursor = 0
    for offset, length in allowed:
        assert original[cursor:offset] == updated[cursor:offset], "Out-of-scope module edit"
        cursor = offset + length
    assert original[cursor:] == updated[cursor:]
    assert len(updated) == len(original)
    return bytes(updated)
