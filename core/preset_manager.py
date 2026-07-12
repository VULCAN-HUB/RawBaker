"""
preset_manager.py — 보정 프리셋 저장/불러오기/삭제

저장 위치:
  - 빌드 exe:  exe 옆 presets/ 폴더
  - 개발 실행: 소스 루트 presets/ 폴더
"""
import json
import sys
from pathlib import Path


def _presets_dir() -> Path:
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent.parent
    d = base / 'presets'
    d.mkdir(exist_ok=True)
    return d


def list_presets() -> list:
    """저장된 프리셋 이름 목록 (알파벳/가나다 정렬)."""
    return sorted(f.stem for f in _presets_dir().glob('*.json'))


def save_preset(name: str, adj: dict) -> None:
    """현재 보정 딕셔너리를 {name}.json 으로 저장. 동명 파일이면 덮어씀."""
    # 파일 이름에 사용 불가한 문자 제거
    safe = "".join(c for c in name if c not in r'\/:*?"<>|').strip()
    if not safe:
        raise ValueError("유효하지 않은 프리셋 이름입니다.")
    path = _presets_dir() / f"{safe}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(adj, f, ensure_ascii=False, indent=2)


def load_preset(name: str) -> dict:
    """이름으로 프리셋 로드. 파일 없으면 FileNotFoundError."""
    path = _presets_dir() / f"{name}.json"
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def delete_preset(name: str) -> None:
    """프리셋 삭제. 없으면 무시."""
    path = _presets_dir() / f"{name}.json"
    if path.exists():
        path.unlink()
