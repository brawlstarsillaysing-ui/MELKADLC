"""Reconstruct the exact, locally signed APK from public release bytes and public literals.

No private signing key, token or signing password is used or stored in this recipe.
The original and output hashes are checked; existing output files are never replaced.
"""

import argparse
import base64
import hashlib
import json
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_branding import patch_module  # noqa: E402


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    recipe = json.loads(Path(__file__).with_name("recipe.json").read_text())
    assert sha(args.original) == recipe["original_sha256"], "Unexpected original APK"
    with args.original.open("rb") as original, args.output.open("xb") as target:
        for segment in recipe["segments"]:
            if segment.get("operation") == "deflate_branded_module":
                with zipfile.ZipFile(args.original) as archive:
                    module = patch_module(archive.read("lib/arm64-v8a/libmodule.so"))
                compressor = zlib.compressobj(level=9, wbits=-15)
                start = target.tell()
                for i in range(0, len(module), 1024 * 1024):
                    target.write(compressor.compress(module[i : i + 1024 * 1024]))
                target.write(compressor.flush())
                assert target.tell() - start == segment["length"], "Unexpected compression output"
            elif "literal" in segment:
                target.write(zlib.decompress(base64.b64decode(segment["literal"], validate=True)))
            else:
                original.seek(segment["offset"])
                remaining = segment["length"]
                while remaining:
                    chunk = original.read(min(1024 * 1024, remaining))
                    assert chunk, "Unexpected end of original"
                    target.write(chunk)
                    remaining -= len(chunk)
    assert sha(args.output) == recipe["apk_sha256"], "Reconstructed APK hash mismatch"
    print("Exact signed APK reconstructed:", recipe["apk_sha256"])


if __name__ == "__main__":
    main()
