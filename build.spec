# -*- mode: python ; coding: utf-8 -*-
# ──────────────────────────────────────────────────────────
# RawBaker build.spec
# 빌드 방법: build.bat 실행  (또는 pyinstaller build.spec --clean --noconfirm)
# 주의: 반드시 이 파일이 있는 폴더(RawBaker\)에서 실행할 것
# ──────────────────────────────────────────────────────────
import os, sys
from pathlib import Path

block_cipher = None

# 현재 spec 파일 위치 기준으로 소스 경로 자동 설정
SRC = os.path.dirname(os.path.abspath(SPEC))

# exe 버전 리소스를 version.py(중앙 상수)에서 생성 — 이중 관리 제거
sys.path.insert(0, SRC)
import version as _ver
_VER_FILE = os.path.join(SRC, "_version_info_generated.txt")
with open(_VER_FILE, "w", encoding="utf-8") as _f:
    _f.write(_ver.windows_version_resource())

# venv 내 numpy.libs DLL 수동 포함 (없으면 DLL load failed 오류 발생)
VENV_SITE = os.path.join(SRC, "venv", "Lib", "site-packages")
NP_LIBS   = os.path.join(VENV_SITE, "numpy.libs")

np_dlls = []
if os.path.isdir(NP_LIBS):
    for f in Path(NP_LIBS).glob("*.dll"):
        np_dlls.append((str(f), "numpy.libs"))

a = Analysis(
    [os.path.join(SRC, 'main.py')],
    pathex=[SRC],
    binaries=np_dlls,
    datas=[
        (os.path.join(SRC, 'assets'), 'assets'),
        (os.path.join(SRC, 'i18n'),   'i18n'),
        (os.path.join(SRC, 'core'),   'core'),
        (os.path.join(SRC, 'ui'),     'ui'),
    ],
    hiddenimports=[
        'rawpy', 'PIL', 'PIL._imaging', 'PIL.Image',
        'PIL.ImageEnhance', 'PIL.ImageFilter', 'PIL.ImageCms',
        'numpy', 'cv2', 'piexif',
    ],
    hookspath=[], runtime_hooks=[], excludes=[],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)

# Exclude interpreter caches from bundled data; Python modules are in PYZ.
a.datas = [entry for entry in a.datas if '__pycache__' not in entry[0].replace('\\', '/').split('/') and not entry[0].endswith(('.pyc', '.pyo'))]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='RawBaker',
    debug=False, strip=False, upx=True, upx_exclude=[],
    runtime_tmpdir=None, console=False,
    icon=os.path.join(SRC, 'assets', 'icon.ico'),
    version=_VER_FILE,   # version.py 에서 생성된 브랜드 메타데이터 (exe 속성 → 자세히)
    onefile=True,
)
