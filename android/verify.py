"""Read-only comparison. Requires androguard==4.1.4; also run Android SDK apksigner verify."""

import argparse
import hashlib
import json
import zipfile

from loguru import logger

logger.remove()
from androguard.core.apk import APK  # noqa: E402
from androguard.core.dex import DEX  # noqa: E402


def instructions(dex, name):
    cls = dex.get_class(name)
    assert cls is not None, name
    return {
        method.get_name() + method.get_descriptor(): [
            (i.get_name(), i.get_output()) for i in method.get_instructions()
        ]
        for method in cls.get_methods()
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original")
    p.add_argument("updated")
    p.add_argument("--old-cert", default="7ed71267a266cfc02225869cfda923f778ace1d497868b57a98fcb9e6ccd088f")
    p.add_argument("--new-cert", required=True)
    args = p.parse_args()
    with zipfile.ZipFile(args.original) as old, zipfile.ZipFile(args.updated) as new:
        assert new.testzip() is None
        for name in ["lib/arm64-v8a/libmodule.so", "lib/arm64-v8a/liblauncher.so", "assets/launch.sh"]:
            assert hashlib.sha256(old.read(name)).digest() == hashlib.sha256(new.read(name)).digest(), name
        original = DEX(old.read("classes.dex"))
        updated = DEX(new.read("classes.dex"))
        for name in ["La/h;", "Lcom/local/moduleloader/StorageServer;"]:
            assert instructions(original, name) == instructions(updated, name), name
        for key, stream in instructions(original, "La/b;").items():
            expected = [(op, value.replace(args.old_cert, args.new_cert)) for op, value in stream]
            assert expected == instructions(updated, "La/b;")[key], key
        assert not any("crack_komarq" in value for value in updated.get_strings())
        config = json.loads(new.read("assets/melkadlc.json"))
    apk = APK(args.updated)
    assert apk.get_package() == "com.local.moduleloader.agnes"
    assert apk.get_app_name() == "MelkaDLC"
    assert apk.get_main_activity() == "com.melkadlc.GateActivity"
    assert apk.is_signed_v2()
    certs = [cert.sha256_fingerprint.replace(" ", "").lower() for cert in apk.get_certificates()]
    assert certs == [args.new_cert]
    print(
        json.dumps(
            {
                "static_comparison": "passed",
                "native_payload": "identical",
                "launcher_script": "identical",
                "loading_and_storage_instructions": "identical",
                "integrity_instructions": "identical_except_authorized_certificate_pin",
                "licensing_enabled": config["licensing_enabled"],
                "runtime_device_tested": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
