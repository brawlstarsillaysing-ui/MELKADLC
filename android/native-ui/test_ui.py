"""Execute the packed ARM64 adapter with mocked existing module drawing APIs.

This validates the actual shipped machine code and ABI, not Android/OpenGL integration.
Run directly: python android/native-ui/test_ui.py (unicorn==2.1.4).
"""

import base64
import hashlib
import json
import struct
import unittest
import zlib
from pathlib import Path

from unicorn import UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm64_const import (
    UC_ARM64_REG_D8,
    UC_ARM64_REG_PC,
    UC_ARM64_REG_S0,
    UC_ARM64_REG_S1,
    UC_ARM64_REG_SP,
    UC_ARM64_REG_X0,
    UC_ARM64_REG_X1,
    UC_ARM64_REG_X2,
    UC_ARM64_REG_X4,
    UC_ARM64_REG_X5,
    UC_ARM64_REG_X6,
    UC_ARM64_REG_X19,
    UC_ARM64_REG_X29,
    UC_ARM64_REG_X30,
)

PACK = json.loads(Path(__file__).with_name("ui-patch.json").read_text())
CODE = zlib.decompress(base64.b64decode(PACK["code_zlib"]))
DATA = 0x20000000
STACK = 0x30000000


def fbits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def fvalue(value):
    return struct.unpack("<f", struct.pack("<I", value))[0]


class ModuleUI:
    def __init__(self, plain=False, base=0):
        self.u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.base, self.plain = base, plain
        self.u.mem_map(DATA, 0x20000)
        self.u.mem_map(STACK, 0x20000)
        for page, size in [
            (PACK["vaddr"], 0x3000),
            (0x7A99000, 0x2000),
            (0x680000, 0x1000),
            (0x5C8000, 0x1000),
            (0x7A7F000, 0x1000),
        ]:
            self.u.mem_map(base + page, size)
        self.u.mem_write(base + PACK["vaddr"], CODE)
        self.stop = DATA + 0xFF00
        self.position = DATA + 0x1000
        self.text = DATA + 0x1100
        self.draw, self.font = DATA + 0x2000, DATA + 0x3000
        self.u.mem_write(self.position, struct.pack("<ff", 100, 80))
        self.u.mem_write(self.draw + 0x38, struct.pack("<Q", DATA + 0x4000))
        self.u.mem_write(DATA + 0x4018, struct.pack("<Q", self.font))
        self.u.mem_write(DATA + 0x4020, struct.pack("<f", 20))
        self.u.mem_write(base + 0x7A99C50, struct.pack("<QQQQ", DATA, DATA + 4, DATA + 8, DATA + 12))
        self.u.mem_write(DATA, b"\xc0\x03\x5f\xd6" * 4)
        self.calls = []
        self.now = 100
        self.site = 0x577F4C if plain else 0x577EF8
        self.handlers = {
            DATA: self.get,
            DATA + 4: self.set,
            DATA + 8: self.caller,
            DATA + 12: self.size,
            base + 0x680450: self.clock,
            base + 0x5C8680: self.measure,
            base + 0x7A7FA50: self.add,
            base + PACK["symbols"]["old_full"]: self.image,
            base + PACK["symbols"]["old_plain"]: self.image,
        }
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def r(self, reg):
        return self.u.reg_read(reg)

    def hook(self, uc, address, size, userdata):
        if address in self.handlers:
            self.handlers[address]()
            uc.reg_write(UC_ARM64_REG_PC, self.r(UC_ARM64_REG_X30))

    def get(self):
        self.u.reg_write(UC_ARM64_REG_X0, self.args.get(self.r(UC_ARM64_REG_X1), 0))

    def set(self):
        self.args[self.r(UC_ARM64_REG_X1)] = self.r(UC_ARM64_REG_X2)

    def caller(self):
        self.u.reg_write(UC_ARM64_REG_X0, self.base + self.site)

    def size(self):
        self.u.reg_write(UC_ARM64_REG_S0, fbits(20))

    def clock(self):
        assert self.r(UC_ARM64_REG_X0) == 1
        sec = int(self.now)
        self.u.mem_write(self.r(UC_ARM64_REG_X1), struct.pack("<qq", sec, round((self.now - sec) * 1e9)))
        self.u.reg_write(UC_ARM64_REG_X0, 0)

    def string(self, begin, end=0):
        result = bytearray()
        for offset in range(128):
            if end and begin + offset >= end:
                break
            value = self.u.mem_read(begin + offset, 1)[0]
            if not value:
                break
            result.append(value)
        return bytes(result)

    def measure(self):
        label = self.string(self.r(UC_ARM64_REG_X1), self.r(UC_ARM64_REG_X2))
        size = fvalue(self.r(UC_ARM64_REG_S0))
        self.u.reg_write(UC_ARM64_REG_S0, fbits(len(label) * size * 0.5))
        self.u.reg_write(UC_ARM64_REG_S1, fbits(size))

    def image(self):
        pos = self.args[1 if self.plain else 2]
        self.calls.append(("image", struct.unpack("<ff", self.u.mem_read(pos, 8))))
        self.args[3 if self.plain else 4] = DATA + 0x1500

    def add(self):
        self.calls.append(
            (
                "text",
                self.string(self.r(UC_ARM64_REG_X4), self.r(UC_ARM64_REG_X5)),
                struct.unpack("<ffff", self.u.mem_read(self.r(UC_ARM64_REG_X6), 16)),
            )
        )

    def frame(self, now, text=b"MelkaDLC", end=None):
        self.now = now
        self.calls = []
        self.u.mem_write(self.text, text + b"\0")
        finish = 0 if end is None else self.text + end
        self.args = (
            {0: self.draw, 1: self.position, 2: 0xFFFFFFFF, 3: self.text, 4: finish}
            if self.plain
            else {0: self.draw, 1: self.font, 2: self.position, 3: 0xFFFFFFFF, 4: self.text, 5: finish}
        )
        self.u.reg_write(UC_ARM64_REG_SP, STACK + 0x1F000)
        self.u.reg_write(UC_ARM64_REG_X0, DATA + 0x5000)
        self.u.reg_write(UC_ARM64_REG_X30, self.stop)
        # AAPCS64 preservation across the public callback.
        registers = [UC_ARM64_REG_X19 + i for i in range(10)] + [UC_ARM64_REG_X29]
        floating = [UC_ARM64_REG_D8 + i for i in range(8)]
        for i, reg in enumerate(registers + floating):
            self.u.reg_write(reg, 0xABC000 + i)
        entry = PACK["plain_entry" if self.plain else "full_entry"]
        self.u.emu_start(self.base + entry, self.stop, timeout=2000000, count=100000)
        assert self.r(UC_ARM64_REG_PC) == self.stop, "UI callback did not finish"
        assert self.r(UC_ARM64_REG_SP) == STACK + 0x1F000
        for i, reg in enumerate(registers + floating):
            assert self.r(reg) == 0xABC000 + i, "ABI callee-saved register changed"
        assert self.args[1 if self.plain else 2] == self.position, "Dangling stack position"
        assert self.u.mem_read(self.position, 8) == struct.pack("<ff", 100, 80)
        return self.calls


class NativeUITests(unittest.TestCase):
    def test_resource_hashes_and_avatar(self):
        self.assertEqual(hashlib.sha256(CODE).hexdigest(), PACK["code_sha256"])
        rgba = zlib.decompress(base64.b64decode(PACK["rgba_zlib"]))
        self.assertEqual(len(rgba), 65536)
        self.assertEqual(hashlib.sha256(rgba).hexdigest(), PACK["rgba_sha256"])
        self.assertEqual(rgba[-14:], bytes(14))

    def test_original_callback_trampoline_destinations(self):
        for name, target in [("old_full", 0x7A7E838), ("old_plain", 0x7A7EA9C)]:
            addr = PACK["symbols"][name]
            first, branch = struct.unpack_from("<II", CODE, addr - PACK["vaddr"])
            self.assertEqual(first, 0xD101C3FF)
            delta = branch & 0x3FFFFFF
            if delta & (1 << 25):
                delta -= 1 << 26
            self.assertEqual(addr + 4 + delta * 4, target)

    def test_loading_reveal_contract_and_aslr(self):
        for plain in [False, True]:
            for base in [0, 0x400000000]:
                with self.subTest(plain=plain, base=base):
                    ui = ModuleUI(plain, base)
                    widths = {}
                    for step in range(21):
                        calls = ui.frame(100 + step * 0.1)
                        self.assertEqual(calls[0][0], "image")
                        words = [c for c in calls if c[0] == "text"]
                        widths[step] = (words[0][2][2] - words[0][2][0]) if words else 0
                        if words:
                            self.assertEqual(words[0][1], b"Melka DLC")
                    self.assertEqual(widths[0], 0)
                    self.assertGreater(widths[6], widths[3])
                    self.assertAlmostEqual(widths[10], 90, places=3)
                    self.assertGreater(widths[14], widths[17])
                    self.assertEqual(widths[20], 0)
                    self.assertEqual(ui.frame(104)[0][1], (100, 80))

    def test_header_uses_static_avatar(self):
        for plain, site in [(False, 0x46E65C), (True, 0x46E6F4)]:
            ui = ModuleUI(plain)
            ui.site = site
            self.assertEqual(ui.frame(100), [("image", (100, 80))])
            self.assertEqual(ui.frame(101), [("image", (100, 80))])

    def test_external_link_labels_hidden(self):
        for plain in [False, True]:
            ui = ModuleUI(plain)
            for text in [
                b"Zenin.cc",
                b"https://ZENIN.CC",
                b"Telegram",
                b"t.me/channel",
                b"@MelkaDLCRealese",
                b"tg:@crack_komarq",
            ]:
                self.assertEqual(ui.frame(100, text), [])
                begin = ui.args[3 if plain else 4]
                self.assertEqual(ui.string(begin), b"")
                self.assertEqual(ui.args[4 if plain else 5], begin)

    def test_other_labels_unchanged_and_end_bounded(self):
        ui = ModuleUI()
        ui.site = 0x12345
        for label in [b"Rage", b"Legit", b"Skins", b"Watermark", b"MelkaDLC"]:
            ui.frame(100, label)
            # The mocked previous callback may handle branding; no adapter text substitution.
            self.assertEqual(ui.calls, [("image", (100, 80))])
        ui.frame(100, b"Watermarkzenin.cc", end=9)
        self.assertEqual(ui.calls, [("image", (100, 80))])


if __name__ == "__main__":
    unittest.main(verbosity=2)
