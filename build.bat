@echo off
setlocal
echo ========================================
echo   RawBaker Build Script
echo ========================================

REM Python 3.12 권장 (py 런처 우선, 없으면 PATH의 python 사용)
set PYEXE=
where py >nul 2>nul && set PYEXE=py -3.12
if not defined PYEXE (
    where python >nul 2>nul && set PYEXE=python
)
if not defined PYEXE (
    echo [ERROR] Python을 찾을 수 없습니다. Python 3.12를 설치하세요.
    echo  설치: winget install Python.Python.3.12
    pause & exit /b 1
)

REM 한글 경로에서는 PyInstaller 6.x가 정션도 실제 경로로 풀어 Qt 플러그인 탐색에 실패한다.
REM → 소스를 ASCII 경로(예: D:\rbbuild)로 복사해 그 안에서 build.bat 을 실행할 것.

if not exist venv (
    echo [1/4] 가상환경 생성 중...
    %PYEXE% -m venv venv
)

echo [2/4] 패키지 설치 중...
call venv\Scripts\activate.bat
pip install -q -r requirements.txt

echo [3/4] PyInstaller 빌드 중...
pyinstaller build.spec --clean --noconfirm

echo [4/4] 완료!
echo.
echo   출력 파일: dist\RawBaker.exe
echo.
pause
endlocal
