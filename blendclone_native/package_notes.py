"""BlendClone native exe packaging recon (DO NOT run full build here).

Build cmd (recon only):
    python -m PyInstaller --noconfirm --windowed --name BlendClone app.py

Expected size: ~250-400MB with Qt (PySide6 + Qt6 DLLs + plugins).
    Mostly Qt6Core/Gui/Widgets/OpenGL + platforms/, styles/, imageformats/.

ARM note (this machine = Snapdragon 8cx, x64-emulated Python):
    Current toolchain builds an x64-emulated exe (runs under emulation).
    Native ARM64 exe needs: ARM64 Python + PySide6 ARM64 wheels + PyInstaller
    run natively, then rebuild. Do not mix x64/ARM64 DLLs.

One-dir vs one-file:
    one-dir (default): faster start, easier DLL debug, ship as folder/zip.
    one-file (--onefile): single exe, slower start (unpack to TEMP),
    worse for Qt + Adreno debugging. Prefer one-dir for now.

Adreno / ANGLE DLL notes:
    Qt6 bundles ANGLE (libEGL.dll, libGLESv2.dll, opengl32sw.dll).
    Keep them next to exe; do not strip. Shaders stay `#version 300 es`
    so both desktop GL and ANGLE paths work. No shadowmap FBO used
    (blob shadow only) to avoid thermal + ANGLE FBO risk.
    If black viewport on Adreno: test QT_OPENGL=angle vs desktop, update
    GPU driver, keep `Qt6/plugins/platforms/qwindows.dll`.

Smoke test plan (after real build, on target machine):
    1. Offscreen: QT_QPA_PLATFORM=offscreen dist/BlendClone/BlendClone.exe
       -- smoke import + QOffscreenSurface render, check exit 0.
    2. Real GPU: launch exe, press 1/2/3 (modes), 4 (shadow toggle),
       add Cube/Sphere, snapshot PNG, check fps in status bar.
    3. Dependency check: missing-DLL popup => inspect dist/BlendClone/
       for platforms/, PySide6/, shiboken6.

Toolchain validated with: `python -m PyInstaller --version` +
    `python -c "from PySide6.QtWidgets import QApplication"`.
Full 5-min build intentionally NOT run in this recon.
"""
