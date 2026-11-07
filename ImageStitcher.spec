# -*- mode: python ; coding: utf-8 -*-

# tkinterdnd2 自带的官方 hook 按当前 OS/架构/Tcl 版本收集对应 tkdnd 文件。
# 用绝对路径加载，避免 PyInstaller 找不到包内的 __pyinstaller 目录。
dnd_hook_dir = r'.venv\Lib\site-packages\tkinterdnd2\__pyinstaller'

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/app.ico', 'assets')],
    hiddenimports=['tkinterdnd2', 'tkinterdnd2.TkinterDnD'],
    hookspath=[dnd_hook_dir],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ImageStitcher',
    icon='assets/app.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
