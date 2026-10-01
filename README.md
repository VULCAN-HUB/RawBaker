# RawBaker

사진 여러 장의 일괄 변환부터 개별 사진 보정과 레이어 디자인까지 한 프로그램에서 작업하기 위해 만드는 로컬 데스크톱 앱입니다.

현재 버전: **Editor 0.25 Preview**. Windows 테스트용이며 macOS는 실제 기기 검증 전입니다.

## 다운로드와 사용법

[릴리스 다운로드](https://github.com/VULCAN-HUB/RawBaker/releases/tag/v0.25-editor-preview)

Windows: `RawBaker-Editor-0.25-Windows-x64.zip`을 풀고 `RawBaker.exe`를 실행합니다. Python 설치는 필요하지 않습니다.

1. 사진을 가져옵니다. 여러 사진은 일괄 보정·출력할 수 있습니다.
2. 보정 화면에서 밝기·색상 등을 조절합니다.
3. 디자인 화면에서 문서를 만들고 사진·텍스트·도형 레이어를 배치합니다.
4. `.rbproj`로 저장하면 원본과 편집 내용을 보관하고 다시 열 수 있습니다.
5. JPEG/PNG 등 필요한 형식으로 내보냅니다.

[자세한 기기 검사 및 빌드 안내](DEVICE-TEST.md)

## 기능과 검증 범위

비파괴 사진 보정, 여러 문서와 레이어, 마스크·변형, 실행 취소/다시 실행, 프로젝트 저장·복구, 일괄 출력. RAW 지원은 카메라와 압축 방식에 따라 다를 수 있습니다.

개발 Windows PC에서 실제RAW9기종과45MP문서출력을 확인했습니다. 다른 Windows PC·macOS·외부 Photoshop/Photon PSD 교환은 미검증입니다. 정식판이 아닌 테스트 버전입니다.

## 제작 및 사용 AI

- 브랜드: **Unknown / VULCAN-HUB**
- GitHub: https://github.com/VULCAN-HUB
- YouTube: https://www.youtube.com/@unknown8563
- 개발에 사용한 AI: **OpenAI Codex (ChatGPT)**

## 개발 환경

Python 3.12, PyQt5, rawpy/LibRaw, NumPy, Pillow, OpenCV, psd-tools, PyInstaller 등을 사용합니다. Windows에서 확인한 버전은 `requirements-windows-studio.txt`를 참조하세요.

Windows 빌드: 가상환경 `venv`에 의존성을 설치하고 `pyinstaller build.spec --clean --noconfirm`을 실행합니다. Mac 빌드는 `bash build_mac.sh`이며 실기 검증 전입니다.

## 공개 범위

프로그램 이름·코드·제작 목적·사용 AI 이름·사용 설명서·공식 GitHub/YouTube 브랜드 정보는 공개합니다. 개인 신원·연락처·주소·인증 정보·비공개 계정 정보·AI 스킬·프롬프트·작업 지시·대화·내부 작업 기록은 공개 자료에 포함하지 않습니다.

## 라이선스

프로젝트: [LICENSE](LICENSE). 동봉 글꼴과 외부 라이브러리는 각각의 라이선스가 적용됩니다. `third-party-licenses`와 `assets/fonts/OFL.txt`를 참조하세요.
