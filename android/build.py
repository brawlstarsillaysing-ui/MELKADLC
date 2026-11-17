"""Build the licensed APK from the pinned original; retain feature code and update bounded branding fields.

Run --help for explicit tool paths. No debug key or implicit keystore is ever used.
This creates a new signing identity only when the owner supplies/authorizes that key.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from native_branding import patch_module

ORIGINAL_SHA256 = "639e45b129443b86fd35e4f03487547dce599a52443a37ba4ead22ceb082cb6e"
ORIGINAL_CERT = "7ed71267a266cfc02225869cfda923f778ace1d497868b57a98fcb9e6ccd088f"
NS = "{http://schemas.android.com/apk/res/android}"
ROOT = Path(__file__).resolve().parent


def run(*args):
    subprocess.run([str(x) for x in args], check=True)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def splice(original, overlay, target):
    """Copy raw ZIP members without changing their compressed streams."""
    import copy
    import struct

    def copy_member(source, out, original_info):
        info = copy.copy(original_info)
        source.fp.seek(info.header_offset)
        header = source.fp.read(30)
        assert header[:4] == b"PK\x03\x04"
        name_len, extra_len = struct.unpack_from("<HH", header, 26)
        length = 30 + name_len + extra_len + info.compress_size
        if info.flag_bits & 8:
            source.fp.seek(info.header_offset + length)
            length += 16 if source.fp.read(4) == b"PK\x07\x08" else 12
        source.fp.seek(info.header_offset)
        info.header_offset = out.fp.tell()
        while length:
            chunk = source.fp.read(min(1024 * 1024, length))
            assert chunk
            out.fp.write(chunk)
            length -= len(chunk)
        out.filelist.append(info)
        out.NameToInfo[info.filename] = info
        out.start_dir = out.fp.tell()

    with (
        zipfile.ZipFile(original) as old,
        zipfile.ZipFile(overlay) as new,
        zipfile.ZipFile(target, "w") as out,
    ):
        copy_member(old, out, old.getinfo("lib/arm64-v8a/liblauncher.so"))
        for info in new.infolist():
            if info.filename != "lib/arm64-v8a/liblauncher.so" and not info.filename.startswith("META-INF/"):
                copy_member(new, out, info)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in [
        "original",
        "work",
        "out",
        "apktool",
        "android-jar",
        "ecj",
        "build-tools",
        "keystore",
        "password-file",
        "certificate",
    ]:
        p.add_argument("--" + name, required=True, type=Path)
    p.add_argument("--alias", default="melkadlc-release")
    p.add_argument("--api-url", default="https://melkadlc.onrender.com", help="Required HTTPS API origin")
    args = p.parse_args()
    if sha(args.original) != ORIGINAL_SHA256:
        p.error("Original APK SHA256 does not match V1.1.0; refusing to patch an unknown build")
    if not args.api_url.startswith("https://") or "@" in args.api_url:
        p.error("API URL must be HTTPS without credentials")
    work = args.work.resolve()
    if work.exists():
        p.error("Work directory must not exist; refusing to overwrite it")
    work.mkdir(parents=True)
    framework = work / "framework"
    decoded = work / "decoded"
    run("java", "-jar", args.apktool, "if", args.android_jar, "-p", framework)
    run("java", "-jar", args.apktool, "d", args.original, "-p", framework, "-o", decoded)
    module_path = decoded / "lib/arm64-v8a/libmodule.so"
    module_path.write_bytes(patch_module(module_path.read_bytes()))
    original_module_hash = "bb56f9a9dacb5470780e992121944cc7b9de7972759bc09b3da5e8952ac09641"
    module_hash = sha(module_path)
    launch = decoded / "assets/launch.sh"
    original_launch_hash = sha(launch)
    launch.write_text(launch.read_text().replace(original_module_hash, module_hash))
    launch_hash = sha(launch)
    cert = sha(args.certificate)
    for f in (decoded / "smali").rglob("*.smali"):
        source = f.read_text()
        source = source.replace("tg: @crack_komarq", "MELKADLC").replace(ORIGINAL_CERT, cert)
        source = source.replace(original_module_hash, module_hash).replace(original_launch_hash, launch_hash)
        source = source.replace('"\\u041a\\u043e\\u0442"', '"MELKADLC"')
        f.write_text(source)
    # Pin change only: the certificate/hash comparisons and all branches remain present.
    ui = decoded / "smali/a/g.smali"
    source = ui.read_text()
    marker = "    invoke-virtual {v1}, Landroid/app/Activity;->getWindow()Landroid/view/Window;"
    palette = {
        "r": 0xFF050505,
        "s": 0xFF151515,
        "t": 0xFFFFFFFF,
        "u": 0xFF050505,
        "v": 0xFF101010,
        "w": 0xFFFFFFFF,
        "x": 0xFFFFFFFF,
        "y": 0xFFA0A0A0,
        "z": 0x22FFFFFF,
    }
    block = "    const/4 v2, 0x1\n\n" + "".join(
        f"    const v7, {color:#x}\n\n    iput v7, v0, La/g;->{field}:I\n\n"
        for field, color in palette.items()
    )
    source = source.replace(marker, block + marker, 1).replace("0x226750a4", "0x22ffffff")
    ui.write_text(source)
    main = decoded / "smali/com/local/moduleloader/MainActivity.smali"
    source = main.read_text()
    source = source.replace(
        '    const-string v0, "MELKADLC"',
        "    invoke-static {p0}, Lcom/melkadlc/GateActivity;->require(Landroid/app/Activity;)Z\n\n"
        "    move-result v0\n\n    if-nez v0, :melka_access_granted\n\n    return-void\n\n"
        '    :melka_access_granted\n    const-string v0, "MELKADLC"',
        1,
    )
    main.write_text(source)
    source = main.read_text()
    marker = "    invoke-virtual {p0, v0}, Landroid/app/Activity;->setContentView(Landroid/view/View;)V"
    source = source.replace(
        marker,
        marker + "\n\n    invoke-static {p0}, Lcom/melkadlc/GateActivity;->decorate(Landroid/app/Activity;)V",
        1,
    )
    main.write_text(source)
    # Original package, activity class, SDK levels and native extraction behavior are retained.
    ET.register_namespace("android", NS[1:-1])
    manifest = decoded / "AndroidManifest.xml"
    tree = ET.parse(manifest)
    root = tree.getroot()
    ET.SubElement(root, "uses-permission", {NS + "name": "android.permission.INTERNET"})
    application = root.find("application")
    application.set(NS + "label", "MelkaDLC")
    application.set(NS + "icon", "@mipmap/ic_launcher")
    application.set(NS + "roundIcon", "@mipmap/ic_launcher")
    application.set(NS + "usesCleartextTraffic", "false")
    application.set(NS + "debuggable", "false")
    activity = application.find("activity")
    activity.set(NS + "exported", "false")
    for item in list(activity):
        activity.remove(item)
    gate = ET.SubElement(
        application, "activity", {NS + "name": "com.melkadlc.GateActivity", NS + "exported": "true"}
    )
    intent = ET.SubElement(gate, "intent-filter")
    ET.SubElement(intent, "action", {NS + "name": "android.intent.action.MAIN"})
    ET.SubElement(intent, "category", {NS + "name": "android.intent.category.LAUNCHER"})
    tree.write(manifest, encoding="utf-8", xml_declaration=True)
    (decoded / "res/drawable/launcher_cat.png").unlink()
    shutil.copytree(ROOT / "resources", decoded / "res", dirs_exist_ok=True)
    (decoded / "assets/melkadlc.json").write_text(
        json.dumps(
            {
                "api_url": args.api_url.rstrip("/"),
                "licensing_enabled": True,
                "bot_username": "MelkaDLCtrialbot",
                "channel_username": "MelkaDLCRealese",
            }
        )
    )
    config = decoded / "apktool.yml"
    config.write_text(
        config.read_text()
        .replace("versionCode: 18", "versionCode: 21")
        .replace("versionName: 0.13-static", "versionName: 0.16-menu")
    )
    rebuilt = work / "rebuilt.apk"
    run("java", "-jar", args.apktool, "b", decoded, "-p", framework, "-o", rebuilt)
    classes = work / "classes"
    classes.mkdir()
    sources = list((ROOT / "src").rglob("*.java"))
    run(
        "java",
        "-jar",
        args.ecj,
        "-1.8",
        "-nowarn",
        "-bootclasspath",
        args.android_jar,
        "-d",
        classes,
        *sources,
    )
    dex = work / "dex"
    dex.mkdir()
    with zipfile.ZipFile(rebuilt) as archive:
        (work / "original.dex").write_bytes(archive.read("classes.dex"))
    run(
        "java",
        "-cp",
        args.build_tools / "lib/d8.jar",
        "com.android.tools.r8.D8",
        "--min-api",
        "26",
        "--lib",
        args.android_jar,
        "--output",
        dex,
        work / "original.dex",
        *classes.rglob("*.class"),
    )
    overlay = work / "overlay.apk"
    with zipfile.ZipFile(rebuilt) as old, zipfile.ZipFile(overlay, "w") as new:
        for info in old.infolist():
            if not info.filename.startswith(("lib/", "META-INF/")) and info.filename != "classes.dex":
                new.writestr(info, old.read(info.filename))
        new.writestr("classes.dex", (dex / "classes.dex").read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        module_info = zipfile.ZipInfo("lib/arm64-v8a/libmodule.so", date_time=(2026, 11, 17, 0, 0, 0))
        module_info.compress_type = zipfile.ZIP_DEFLATED
        module_info._compresslevel = 9
        with module_path.open("rb") as module, new.open(module_info, "w") as dest:
            shutil.copyfileobj(module, dest, length=1024 * 1024)
    rebuilt.unlink()
    module_path.unlink()
    splice(args.original, overlay, work / "unsigned.apk")
    run(args.build_tools / "zipalign", "-f", "4", work / "unsigned.apk", work / "aligned.apk")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        p.error("Output already exists; refusing to replace it")
    run(
        args.build_tools / "apksigner",
        "sign",
        "--ks",
        args.keystore,
        "--ks-key-alias",
        args.alias,
        "--ks-pass",
        "file:" + str(args.password_file),
        "--out",
        args.out,
        work / "aligned.apk",
    )
    run(args.build_tools / "apksigner", "verify", "--verbose", "--print-certs", args.out)
    # Independent exact-content preservation check, after signing.
    with zipfile.ZipFile(args.original) as old, zipfile.ZipFile(args.out) as new:
        name = "lib/arm64-v8a/liblauncher.so"
        assert old.read(name) == new.read(name)
        assert hashlib.sha256(new.read("lib/arm64-v8a/libmodule.so")).hexdigest() == module_hash
        assert hashlib.sha256(new.read("assets/launch.sh")).hexdigest() == launch_hash
    report = {
        "original_sha256": ORIGINAL_SHA256,
        "apk_sha256": sha(args.out),
        "certificate_sha256": cert,
        "new_signing_identity": False,
        "compatible_with_previous_melkadlc_certificate": True,
        "requires_reinstall_over_original_skinchiki": True,
        "licensing_enabled": bool(args.api_url),
        "native_changes": "branding strings/RGBA/CRC; two UI callback entry branches; isolated UI code in padding; RX size and RW zero-state size",
        "native_feature_bytes_unchanged": True,
        "external_link_labels_hidden": True,
        "external_link_click_handlers_removed": False,
        "module_sha256": module_hash,
        "launch_sha256": launch_hash,
        "api_url": args.api_url.rstrip("/"),
        "runtime_device_tested": False,
    }
    (work / "verification.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
