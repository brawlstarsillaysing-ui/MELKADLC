"""Pinned, bounded edits to the existing module's branding data and its expected CRC.

The loader, exported functions, hooks, relocations and feature instructions are retained.
No integrity comparison is disabled: the expected branding-data CRC is updated.
"""

import hashlib
import struct
import zlib

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
    strings = [(0, b"crack_komarq\0", b"MelkaDLC\0"), (13, b"tg:@crack_komarq\0", b"@MelkaDLCRealese\0")]
    for start, before, after in strings:
        plain = bytes(original[BRANDING_OFFSET + start + i] ^ mask(start + i) for i in range(len(before)))
        assert plain == before, "Unexpected branding data"
        assert len(after) <= len(before), "Brand exceeds fixed slot"
        for i, value in enumerate(after.ljust(len(before), b"\0")):
            updated[BRANDING_OFFSET + start + i] = value ^ mask(start + i)
    expected = zlib.crc32(updated[BRANDING_OFFSET : BRANDING_OFFSET + BRANDING_SIZE]) ^ 0xFFFFFFFF
    # ARM64 MOVZ/MOVK only: change the embedded release CRC, retaining opcode, register and shift.
    for offset, shift, previous in [(CRC_LOW_OFFSET, 0, 0x98F9), (CRC_HIGH_OFFSET, 16, 0x0738)]:
        word = struct.unpack_from("<I", original, offset)[0]
        assert (word >> 5) & 0xFFFF == previous, "Unexpected CRC constant"
        word = (word & ~(0xFFFF << 5)) | (((expected >> shift) & 0xFFFF) << 5)
        struct.pack_into("<I", updated, offset, word)
    return bytes(updated)
