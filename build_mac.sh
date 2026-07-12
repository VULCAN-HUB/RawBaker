#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────
# RawBaker macOS 빌드 스크립트 (Mac 실기에서 실행)
# 결과: dist/RawBaker.app  (필요 시 .dmg 는 아래 주석 참고)
# 전제: Python 3.12 설치(brew install python@3.12 또는 python.org)
# ※ Mac 은 한글 경로 빌드 문제 없음 — 소스 폴더에서 바로 실행 가능.
# ──────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
echo "[1/3] 가상환경 준비..."
if [ ! -d "venv_mac" ]; then
  "$PY" -m venv venv_mac
fi
source venv_mac/bin/activate

echo "[2/3] 패키지 설치..."
pip install --upgrade pip -q
pip install -q -r requirements.txt

echo "[3/3] PyInstaller 빌드(.app)..."
pyinstaller build_mac.spec --clean --noconfirm

echo
echo "완료: dist/RawBaker.app"
echo
# ── .dmg 만들기(선택) ─────────────────────────────────────
# brew install create-dmg
# create-dmg --volname "RawBaker" --window-size 500 300 \
#   --app-drop-link 360 120 dist/RawBaker.dmg dist/RawBaker.app
#
# ── 코드서명/공증(배포 시, Apple Developer 계정 필요) ────────
# codesign --deep --force --options runtime --sign "Developer ID Application: ..." dist/RawBaker.app
# xcrun notarytool submit ... ; xcrun stapler staple dist/RawBaker.app
