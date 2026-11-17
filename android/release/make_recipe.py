"""Save public delivery metadata for an APK already signed locally; never reads a signing key."""

import argparse
import base64
import hashlib
import json
import struct
import zipfile
import zlib
from pathlib import Path


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def data_offset(stream, info):
    stream.seek(info.header_offset + 26)
    name, extra = struct.unpack("<HH", stream.read(4))
    return info.header_offset + 30 + name + extra


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original", type=Path)
    p.add_argument("updated", type=Path)
    p.add_argument("verification", type=Path)
    args = p.parse_args()
    report = json.loads(args.verification.read_text())
    assert sha(args.original) == report["original_sha256"]
    assert sha(args.updated) == report["apk_sha256"]
    with (
        zipfile.ZipFile(args.original) as old,
        zipfile.ZipFile(args.updated) as new,
        args.original.open("rb") as source,
        args.updated.open("rb") as updated,
    ):
        module = new.getinfo("lib/arm64-v8a/libmodule.so")
        spans = [
            (
                data_offset(updated, module),
                {"operation": "deflate_branded_module", "length": module.compress_size},
            )
        ]
        helper = new.getinfo("lib/arm64-v8a/liblauncher.so")
        previous = old.getinfo(helper.filename)
        assert previous.compress_size == helper.compress_size
        spans.append(
            (
                data_offset(updated, helper),
                {"offset": data_offset(source, previous), "length": helper.compress_size},
            )
        )
        segments = []
        cursor = 0
        for offset, operation in sorted(spans):
            if offset > cursor:
                updated.seek(cursor)
                segments.append(
                    {"literal": base64.b64encode(zlib.compress(updated.read(offset - cursor), 9)).decode()}
                )
            segments.append(operation)
            cursor = offset + operation["length"]
        updated.seek(cursor)
        tail = updated.read()
        if tail:
            segments.append({"literal": base64.b64encode(zlib.compress(tail, 9)).decode()})
        report["segments"] = segments
        report["asset_name"] = args.updated.name
        Path(__file__).with_name("recipe.json").write_text(json.dumps(report, indent=2) + "\n")
        print("Public recipe created for", args.updated.name)


if __name__ == "__main__":
    main()
