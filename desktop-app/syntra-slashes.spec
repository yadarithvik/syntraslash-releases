# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('index.html', '.'), ('model-setup.html', '.'), ('guardrails.json', '.'), ('assets', 'assets'), ('builtin_skills','builtin_skills')],
    hiddenimports=['mcp_client','local_schedule','extensions','document_readers','pypdf','diagnostics', 'memory_engine', 'bundled_engine', 'desktop_agent', 'pyautogui', 'PIL', 'win32gui', 'win32con', 'win32api', 'win32clipboard', 'comtypes', 'session_store', 'session_manager', 'event_bus', 'desktop_coordinator', 'authorization', 'perception', 'tools_registry', 'model_bridge', 'runtime_discovery', 'engine', 'sqlite3', 'webview'],
    hookspath=[],
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
    name='syntra-slashes',
    icon='assets/syntra.ico',
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
