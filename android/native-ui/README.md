# Native menu adapter

This adapter is specific to the pinned V1.1.0 ARM64 module. It only uses the existing
branding/drawing callbacks and the module's monotonic clock import. No game state,
input handling, license API or loading/menu transition is implemented here.

`ui.c`, `entry.S`, `link.ld` are the complete adapter sources. `avatar.svg` matches the
APK icon; `ui-patch.json` contains the compiled public code and 128×128 RGBA bitmap,
compressed with hashes. The last fourteen RGBA bytes are zero to match the existing
decoder. Release reconstruction uses Python stdlib and this resource; no compiler
or private signing material is needed.

To rebuild the packed code (the existing bitmap is retained):

```sh
pip install ziglang==0.17.1 pyelftools==0.33 unicorn==2.1.4
python android/native-ui/build.py --out /tmp/melkadlc-ui
python android/native-ui/test_ui.py
```

The original two callback prologues are preserved in assembly trampolines. The
entry adapters preserve AAPCS64 and compute the module base using PC-relative
addressing. Animation is driven by monotonic time, without a delay or a loading
state change. The original menu transition remains controlled by the original
module. Link filtering applies only to visible AddText labels; it does not prove
deletion of the underlying button/input handler. Unicorn tests mock the module's
existing APIs and do not replace Android/OpenGL device testing.
