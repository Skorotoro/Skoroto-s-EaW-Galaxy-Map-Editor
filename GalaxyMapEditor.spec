# -*- mode: python ; coding: utf-8 -*-
# Folder build: GalaxyMapEditor.exe plus its files in _internal (no self-unpacking).

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('editor.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pygame', 'numpy', 'lupa'],
    noarchive=False,
    optimize=0,
)

# Leave out the runtime files the editor never uses (time zones, translations, logos, test tools).
KEEP_ENC = ('ascii.enc', 'cp1252.enc', 'iso8859-1.enc')
DROP = ('_tcl_data/tzdata/', '_tcl_data/msgs/', '_tk_data/images/', '_tk_data/msgs/', 'tcl8/8.5/tcltest',
        'tcl8/8.6/http', 'tcl8/8.4/', 'PIL/_avif', 'PIL/_webp', 'PIL/_imagingcms', 'api-ms-win-')


def wanted(entry):
    name = entry[0].replace('\\', '/')
    if name.startswith(DROP):
        return False
    if name.startswith('_tcl_data/encoding/') and not name.endswith(KEEP_ENC):
        return False
    return True


a.datas = [d for d in a.datas if wanted(d)]
a.binaries = [b for b in a.binaries if wanted(b)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GalaxyMapEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['editor.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Galaxy Map Editor',
)
