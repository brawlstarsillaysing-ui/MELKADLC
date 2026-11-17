"""Read-only comparison. Requires androguard==4.1.4; also run Android SDK apksigner verify."""

import argparse
import hashlib
import json
import zipfile

from loguru import logger

logger.remove()
from androguard.core.apk import APK  # noqa: E402
from androguard.core.dex import DEX  # noqa: E402
from native_branding import patch_module  # noqa: E402


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
    p.add_argument("--previous", help="Previous licensed MelkaDLC APK for license-instruction comparison")
    args = p.parse_args()
    with zipfile.ZipFile(args.original) as old, zipfile.ZipFile(args.updated) as new:
        assert new.testzip() is None
        assert old.read("lib/arm64-v8a/liblauncher.so") == new.read("lib/arm64-v8a/liblauncher.so")
        old_module = old.read("lib/arm64-v8a/libmodule.so")
        new_module = new.read("lib/arm64-v8a/libmodule.so")
        assert patch_module(old_module) == new_module
        old_hash = hashlib.sha256(old_module).hexdigest()
        new_hash = hashlib.sha256(new_module).hexdigest()
        old_launch = old.read("assets/launch.sh")
        new_launch = new.read("assets/launch.sh")
        assert old_launch.replace(old_hash.encode(), new_hash.encode()) == new_launch
        pins = {
            args.old_cert: args.new_cert,
            old_hash: new_hash,
            hashlib.sha256(old_launch).hexdigest(): hashlib.sha256(new_launch).hexdigest(),
        }
        original = DEX(old.read("classes.dex"))
        updated = DEX(new.read("classes.dex"))
        for name in ["La/h;", "Lcom/local/moduleloader/StorageServer;"]:
            assert instructions(original, name) == instructions(updated, name), name
        for key, stream in instructions(original, "La/b;").items():
            expected = []
            for op, value in stream:
                for before, after in pins.items():
                    value = value.replace(before, after)
                expected.append((op, value))
            assert expected == instructions(updated, "La/b;")[key], key
        assert not any("crack_komarq" in value for value in updated.get_strings())
        assert not any("github.com" in value.lower() for value in updated.get_strings())
        config = json.loads(new.read("assets/melkadlc.json"))
        assert config["licensing_enabled"] is True
        assert config["api_url"] == "https://melkadlc.onrender.com"
        if args.previous:
            with zipfile.ZipFile(args.previous) as previous:
                prior = DEX(previous.read("classes.dex"))
                for name in ["Lcom/melkadlc/LicenseLease;", "Lcom/melkadlc/GateActivity;"]:
                    expected = {
                        key: [(op, value.replace("0.15-licensed", "0.16-menu")) for op, value in stream]
                        for key, stream in instructions(prior, name).items()
                    }
                    assert expected == instructions(updated, name), "License instructions changed: " + name
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
                "native_payload": "bounded branding/bitmap/CRC, two UI callbacks and isolated padding adapter; all other bytes identical",
                "previous_license_instructions": "identical except display version"
                if args.previous
                else "not compared",
                "external_link_click_handlers_removed": False,
                "launcher_script": "only expected module hash changed",
                "loading_and_storage_instructions": "identical",
                "integrity_instructions": "identical except authorized certificate and content pins",
                "licensing_enabled": config["licensing_enabled"],
                "runtime_device_tested": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
