"""Compile the isolated AArch64 UI adapter and pack its public code/bitmap resources.

Authoring dependencies: ziglang==0.17.1, pyelftools. Release reconstruction only needs Python stdlib.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parent
START = 0x7A81000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rgba", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["ZIG_GLOBAL_CACHE_DIR"] = str(args.out / "zig-cache")
    env["ZIG_LOCAL_CACHE_DIR"] = str(args.out / "zig-local")
    elf = args.out / "ui.elf"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ziglang",
            "cc",
            "-target",
            "aarch64-freestanding-none",
            "-Os",
            "-g",
            "-ffreestanding",
            "-fPIC",
            "-fvisibility=hidden",
            "-fno-stack-protector",
            "-fno-unwind-tables",
            "-fno-asynchronous-unwind-tables",
            "-nostdlib",
            "-Wl,-T," + str(ROOT / "link.ld"),
            "-Wl,-e,melka_full_entry",
            "-Wl,--build-id=none",
            str(ROOT / "entry.S"),
            str(ROOT / "ui.c"),
            "-o",
            str(elf),
        ],
        env=env,
        check=True,
    )
    with elf.open("rb") as stream:
        image = ELFFile(stream)
        allocated = [s for s in image.iter_sections() if s["sh_flags"] & 2 and s["sh_size"]]
        end = max(s["sh_addr"] + s["sh_size"] for s in allocated)
        assert min(s["sh_addr"] for s in allocated) == START
        assert end < 0x7A84000, "UI adapter exceeds reserved padding"
        blob = bytearray(end - START)
        for section in allocated:
            assert not section["sh_flags"] & 1, "Unexpected writable code resource"
            off = section["sh_addr"] - START
            blob[off : off + section["sh_size"]] = section.data()
        symbols = {s.name: s["st_value"] for s in image.get_section_by_name(".symtab").iter_symbols()}
    resource = ROOT / "ui-patch.json"
    if args.rgba:
        rgba = args.rgba.read_bytes()
    else:
        previous = json.loads(resource.read_text())
        rgba = zlib.decompress(base64.b64decode(previous["rgba_zlib"]))
    assert len(rgba) == 128 * 128 * 4 and rgba[-14:] == bytes(14)
    payload = {
        "vaddr": START,
        "file_offset": 0x75BD000,
        "full_entry": symbols["melka_full_entry"],
        "plain_entry": symbols["melka_plain_entry"],
        "state_vaddr": 0x7A9A000,
        "code_sha256": hashlib.sha256(blob).hexdigest(),
        "code_zlib": base64.b64encode(zlib.compress(blob, 9)).decode(),
        "rgba_sha256": hashlib.sha256(rgba).hexdigest(),
        "rgba_zlib": base64.b64encode(zlib.compress(rgba, 9)).decode(),
        "symbols": {n: symbols[n] for n in ["old_full", "old_plain", "melka_phase", "melka_link_label"]},
    }
    resource.write_text(json.dumps(payload, indent=2) + "\n")
    print("Packed UI adapter:", len(blob), "bytes; avatar:", len(rgba), "bytes")


if __name__ == "__main__":
    main()
