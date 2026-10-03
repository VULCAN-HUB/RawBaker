# RawBaker

**테스트 중 · v0.25-editor-preview · 정식 출시 전**

사진 여러 장의 일괄 변환부터 개별 사진 보정과 레이어 디자인까지 한곳에서 작업하는 로컬 데스크톱 앱입니다.

**[다운로드](https://github.com/VULCAN-HUB/RawBaker/releases/tag/v0.25-editor-preview)** · **[사용 안내](DEVICE-TEST.md)**

제작: **Unknown** · [홈페이지](https://vulcan-hub.github.io/) · [YouTube](https://www.youtube.com/@unknown8563)

## 기능

- 비파괴 사진 보정과 여러 사진의 일괄 출력을 지원합니다.
- 여러 문서와 사진·텍스트·도형 레이어, 마스크·변형을 다룹니다.
- 실행 취소·다시 실행과 프로젝트 저장·복구를 지원합니다.

## 요구사항과 상태

| 항목 | 내용 |
|---|---|
| 실행 환경 | Windows 10/11 x64 · 배포 ZIP 사용 시 Python 설치 불필요 |
| 배포 형태 | Windows ZIP · macOS 빌드용 소스 제공, 앱 미검증 |

개발 Windows PC에서 실제 RAW 9기종과 45MP 문서 출력을 확인했습니다. 다른 Windows PC·macOS·외부 Photoshop/Photon PSD 교환은 미검증입니다. RAW 지원은 카메라와 압축 방식에 따라 다를 수 있습니다.

## 사용법

Windows: `RawBaker-Editor-0.25-Windows-x64.zip`을 풀고 `RawBaker.exe`를 실행합니다. Python 설치는 필요하지 않습니다.

1. 사진을 가져옵니다. 여러 사진은 일괄 보정·출력할 수 있습니다.
2. 보정 화면에서 밝기·색상 등을 조절합니다.
3. 디자인 화면에서 문서를 만들고 사진·텍스트·도형 레이어를 배치합니다.
4. `.rbproj`로 저장하면 원본과 편집 내용을 보관하고 다시 열 수 있습니다.
5. JPEG/PNG 등 필요한 형식으로 내보냅니다.

[자세한 기기 검사 및 빌드 안내](DEVICE-TEST.md)

## 개발 환경

Python 3.12, PyQt5, rawpy/LibRaw, NumPy, Pillow, OpenCV, psd-tools, PyInstaller 등을 사용합니다. Windows에서 확인한 버전은 `requirements-windows-studio.txt`를 참조하세요.

Windows 빌드: 가상환경 `venv`에 의존성을 설치하고 `pyinstaller build.spec --clean --noconfirm`을 실행합니다. Mac 빌드는 `bash build_mac.sh`이며 실기 검증 전입니다.

개발에 사용한 AI: **OpenAI Codex (ChatGPT)**.

## 라이선스·공개 정책

프로젝트: [LICENSE](LICENSE). 동봉 글꼴과 외부 라이브러리는 각각의 라이선스가 적용됩니다. `third-party-licenses`와 `assets/fonts/OFL.txt`를 참조하세요.

[보안 취약점 신고](SECURITY.md) · [게시 전 체크리스트](PUBLICATION_CHECKLIST.md) · [AI 및 자동화 행동 규칙](AI_AUTOMATION_RULES.md)

[공개 정책: VULCAN-0.3](https://github.com/VULCAN-HUB/RawBaker/blob/main/PUBLICATION_POLICY.md)
