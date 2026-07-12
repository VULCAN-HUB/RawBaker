# -*- mode: python ; coding: utf-8 -*-
# ──────────────────────────────────────────────────────────
# RawBaker macOS build.spec  (.app 번들)
# 빌드: Mac 실기에서  ./build_mac.sh  (또는 pyinstaller build_mac.spec --clean --noconfirm)
# ※ 이 spec 은 macOS 에서만 의미가 있다. Windows 빌드는 build.spec 사용.
#   numpy.libs DLL 수동 주입은 Windows 전용이라 여기서는 하지 않는다(맥은 PyInstaller가 .dylib 처리).
# ──────────────────────────────────────────────────────────
import os, sys
block_cipher = None

SRC = os.path.dirname(os.path.abspath(SPEC))

# 버전 정보(중앙 상수)
sys.path.insert(0, SRC)
import version as _ver

a = Analysis(
    [os.path.join(SRC, 'main.py')],
    pathex=[SRC],
    binaries=[],
    datas=[
        (os.path.join(SRC, 'assets'), 'assets'),
        (os.path.join(SRC, 'i18n'),   'i18n'),
        (os.path.join(SRC, 'core'),   'core'),
        (os.path.join(SRC, 'ui'),     'ui'),
    ],
    hiddenimports=[
        'rawpy', 'PIL', 'PIL._imaging', 'PIL.Image',
        'PIL.ImageEnhance', 'PIL.ImageFilter', 'PIL.ImageCms',
        'numpy', 'cv2', 'piexif', 'psutil',
    ],
    hookspath=[], runtime_hooks=[], excludes=[],
    cipher=block_cipher, noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# macOS 는 onefile 대신 onedir + BUNDLE(.app) 권장 (Gatekeeper·서명·실행 안정성)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='RawBaker',
    debug=False, strip=False, upx=False, console=False,
    icon=os.path.join(SRC, 'assets', 'icon.icns'),
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name='RawBaker',
)

app = BUNDLE(
    coll,
    name='RawBaker.app',
    icon=os.path.join(SRC, 'assets', 'icon.icns'),
    bundle_identifier='com.johheunsaram.rawbaker',
    version=_ver.VERSION_DISPLAY,
    info_plist={
        'CFBundleName': _ver.APP_NAME,
        'CFBundleDisplayName': _ver.APP_NAME,
        'CFBundleShortVersionString': _ver.VERSION_DISPLAY,
        'NSHumanReadableCopyright': _ver.COPYRIGHT,
        'NSHighResolutionCapable': True,
    },
)
