# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp/cabinet_studio/library', 'cabinet_studio/library'), ('C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp/cabinet_studio/programs', 'cabinet_studio/programs')]
binaries = []
hiddenimports = ['cabinet_studio.services.ladder_sim', 'cabinet_studio.services.plcopen_xml', 'cabinet_studio.services.ladder_ir', 'cabinet_studio.ui.programming_viewer']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp/app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='CabinetStudio-0.3.1',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CabinetStudio-0.3.1',
)
