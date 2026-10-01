"""앱 버전·브랜드 중앙 상수 (단일 진실 공급원).

About 다이얼로그 · 창 제목 · exe 버전 리소스가 모두 이 파일을 참조한다.
버전을 올릴 때는 여기 값만 바꾸면 된다.

예) 정식 1.0 전환:
    VERSION_TUPLE   = (1, 0, 0, 0)
    IS_BETA         = False
    VERSION_DISPLAY = "1.0.0.0"
"""

APP_NAME        = "RawBaker"
VERSION_TUPLE   = (0, 25, 0, 0)          # exe 숫자 버전 (정수 4-튜플만 허용)
IS_BETA         = True
VERSION_DISPLAY = "BETA Ver-0.25 Editor Preview" # 사람이 보는 표기 (About·exe FileVersion 문자열)
COMPANY         = "Unknown"
YEAR            = "2026"
COPYRIGHT       = "© 2026 Unknown"
DESCRIPTION     = "RawBaker — 사진 변환·보정·디자인"


def windows_version_resource() -> str:
    """PyInstaller용 Windows 버전 리소스(VSVersionInfo) 텍스트 생성.
    build.spec 이 이 값을 받아 임시 파일로 써서 EXE(version=...)에 넘긴다.
    → version_info 를 별도 파일로 이중 관리하지 않고 이 상수에서 단일 생성."""
    fv = ", ".join(str(n) for n in VERSION_TUPLE)
    return f"""# 자동 생성됨 — version.py 의 windows_version_resource() 가 만든다. 직접 수정 금지.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({fv}),
    prodvers=({fv}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '041204b0',
          [
            StringStruct('CompanyName', '{COMPANY}'),
            StringStruct('FileDescription', '{DESCRIPTION}'),
            StringStruct('FileVersion', '{VERSION_DISPLAY}'),
            StringStruct('InternalName', '{APP_NAME}'),
            StringStruct('LegalCopyright', '{COPYRIGHT}'),
            StringStruct('OriginalFilename', '{APP_NAME}.exe'),
            StringStruct('ProductName', '{APP_NAME}'),
            StringStruct('ProductVersion', '{VERSION_DISPLAY}')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""

