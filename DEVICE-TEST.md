# RawBaker Editor 0.27 — 기기 테스트 버전

브랜드: Unknown / @unknown8563. Windows x64 테스트용 미리보기입니다.

## Windows

RawBaker-Editor-0.27-Windows-x64.zip 전체를 풀고 RawBaker.exe를 실행합니다. Python 설치는 필요하지 않습니다.
자동 검사: 압축을 푼 폴더에서 PowerShell을 열고 아래 명령을 실행합니다.

```powershell
& '.\Verify-Windows.ps1' -ReleaseDirectory (Get-Location).Path
```

파일 해시와 한국어/영어 실행을 검사하고 옆의 RawBaker check-… 폴더에 report.json을 생성합니다. success:true인지 확인하세요. 검사 결과는 자동 전송되지 않습니다. 조직의 실행 정책을 임의로 변경하지 마세요.

수동 확인: 화면 배율·사진 가져오기·보정·프로젝트 저장/재열기·JPEG/PNG 출력·언어 전환 후 재시작. 오류가 있으면 OS/배율/메모리/재현 단계와 검사 결과를 보관하세요.

## macOS

아직 검증된 .app/.dmg는 없습니다. RawBaker-Editor-0.27-source.zip을 풀고 Python 3.12가 설치된 실제 Mac의 터미널에서 실행합니다.

```bash
bash build_mac.sh
```

완성 경로: dist/RawBaker.app. 실제 Mac 빌드/서명/공증/실행은 미검증입니다. CPU 아키텍처·Retina·Cmd 단축키·한글·저장/출력을 확인해야 합니다.

## 검증 범위

개발 Windows PC에서 301회귀 통과(환경 관련1skip/1제외), 기존 EXE 한국어/영어 각31검사 통과. 실제 RAW9기종(CR3/NEF/ARW/DNG), 3개45MP급 문서, 저장/재열기, 원본JPEG9장, 문서JPEG/PNG16 통과. 다른Windows/Mac 및 Photoshop/Photon PSD 실교환은 미검증입니다. 모든카메라압축모드나모든PSD기능의호환보장은아닙니다.

사진 원본·개인 프로젝트·개발 PC 로그는 배포에 포함하지 않습니다. 라이선스는 LICENSE와 third-party-licenses를 참조하세요.

## 앱 업데이트 검사

상단 `?`에서 YouTube·Discord·글꼴 라이선스·현재 버전을 확인하세요. 업데이트 확인은 다운로드를 자동으로 시작하지 않습니다. 현재 버전보다 새 버전과 일치하는 Windows x64 ZIP이 있을 때만 다운로드를 제공합니다. ZIP 자동 설치와 Mac 업데이트는 미지원입니다.

검증된 파일 폴더를 연 뒤, 작업을 저장하고 앱을 종료하여 새 폴더에 ZIP을 풀어 실행하세요. 프로젝트·원본·설정은 보존하세요. 0.25의 첫 업그레이드는 홈페이지에서 직접 다운로드합니다.

알려진 제한: 일부 손상된 프로젝트 오류는 영어 UI에서도 한국어로 표시될 수 있습니다.
