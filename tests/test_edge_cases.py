"""
Edge case tests: 한글 경로, 특수문자, 경로 길이 초과, 읽기전용 폴더.
"""
import os, sys, stat, shutil, tempfile
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.converter import convert_file, ConvertError, validate_output_dir

TEST_IMAGES = Path(__file__).parent.parent / 'test_images'
SRC = str(TEST_IMAGES / 'small_exif.jpg')


# ──────────────────────────────────────────────────────────────
# 1. 한글 경로
# ──────────────────────────────────────────────────────────────
class TestKoreanPath:
    def test_korean_output_folder(self, tmp_path):
        kor_dir = tmp_path / "사진변환_폴더"
        kor_dir.mkdir()
        out = convert_file(SRC, str(kor_dir), 'JPEG')
        assert os.path.exists(out), "한글 경로 출력 실패"

    def test_special_chars_folder(self, tmp_path):
        """특수문자 포함 경로 (Windows 허용 범위 내)"""
        sp_dir = tmp_path / "photos (2024) & more"
        sp_dir.mkdir()
        out = convert_file(SRC, str(sp_dir), 'JPEG')
        assert os.path.exists(out)

    def test_deep_korean_nested(self, tmp_path):
        """한글 다단 중첩 경로"""
        deep = tmp_path / "사진" / "2024년" / "봄"
        deep.mkdir(parents=True)
        out = convert_file(SRC, str(deep), 'PNG')
        assert os.path.exists(out)


# ──────────────────────────────────────────────────────────────
# 2. 경로 길이 초과 (260자 제한)
# ──────────────────────────────────────────────────────────────
class TestPathLength:
    def test_output_dir_near_limit_is_ok(self, tmp_path):
        """250자 이하 경로 — 정상 처리"""
        long_name = "a" * 40
        d = tmp_path / long_name
        d.mkdir()
        out = convert_file(SRC, str(d), 'JPEG')
        assert os.path.exists(out)

    def test_output_dir_too_long_raises(self):
        """260자 초과 경로 — ConvertError 발생"""
        very_long = "C:\\" + "a" * 250
        with pytest.raises(ConvertError, match="너무 깁니다"):
            validate_output_dir(very_long)

    def test_output_dir_exactly_limit(self):
        """경계값: 240자 경로 — validate만 테스트"""
        at_limit = "C:\\" + "a" * 237   # 총 240자
        with pytest.raises(ConvertError):
            validate_output_dir(at_limit)


# ──────────────────────────────────────────────────────────────
# 3. 읽기 전용 폴더
# ──────────────────────────────────────────────────────────────
class TestReadOnlyFolder:
    def test_readonly_folder_raises_convert_error(self, tmp_path):
        """읽기 전용 폴더에 저장 시도 → ConvertError, 프로그램 튕김 없음.
        Windows에서 관리자 권한이면 chmod가 무시되므로 icacls로 제한."""
        import subprocess
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        # icacls로 현재 유저의 Write 권한 제거
        user = os.environ.get('USERNAME', 'Everyone')
        result = subprocess.run(
            ['icacls', str(ro_dir), '/deny', f'{user}:(W)'],
            capture_output=True
        )
        if result.returncode != 0:
            pytest.skip("icacls 권한 설정 실패 (권한 부족)")
        try:
            with pytest.raises(ConvertError, match="저장할 수 없습니다"):
                validate_output_dir(str(ro_dir))
        finally:
            subprocess.run(['icacls', str(ro_dir), '/remove:d', user], capture_output=True)

    def test_nonexistent_folder_is_created(self, tmp_path):
        """존재하지 않는 폴더 → 자동 생성"""
        new_dir = tmp_path / "new_output_dir"
        assert not new_dir.exists()
        validate_output_dir(str(new_dir))
        assert new_dir.exists()


# ──────────────────────────────────────────────────────────────
# 4. 잘못된 파일 / 손상된 이미지
# ──────────────────────────────────────────────────────────────
class TestCorruptFile:
    def test_corrupt_jpeg_raises_convert_error(self, tmp_path):
        """손상된 JPEG → ConvertError, 크래시 없음"""
        bad = tmp_path / "corrupt.jpg"
        bad.write_bytes(b"This is not a JPEG file at all" * 100)
        with pytest.raises(ConvertError):
            convert_file(str(bad), str(tmp_path), 'PNG')

    def test_empty_file_raises_convert_error(self, tmp_path):
        """빈 파일 → ConvertError"""
        empty = tmp_path / "empty.png"
        empty.write_bytes(b"")
        with pytest.raises(ConvertError):
            convert_file(str(empty), str(tmp_path), 'JPEG')

    def test_wrong_extension_raises(self, tmp_path):
        """지원하지 않는 확장자 → ConvertError"""
        txt = tmp_path / "photo.txt"
        txt.write_text("not an image")
        with pytest.raises(ConvertError, match="지원하지 않는"):
            convert_file(str(txt), str(tmp_path), 'JPEG')

    def test_jpeg_disguised_as_png(self, tmp_path):
        """JPEG 바이트를 .png 로 저장 → Pillow가 처리 가능해야 함"""
        from PIL import Image
        import io
        img = Image.new('RGB', (100, 100), (200, 100, 50))
        buf = io.BytesIO()
        img.save(buf, 'JPEG')
        bad = tmp_path / "actually_jpeg.png"
        bad.write_bytes(buf.getvalue())
        # Pillow는 magic bytes로 감지하므로 정상 처리
        out = convert_file(str(bad), str(tmp_path), 'JPEG')
        assert os.path.exists(out)


# ──────────────────────────────────────────────────────────────
# 5. 동시 접근 안전성
# ──────────────────────────────────────────────────────────────
class TestConcurrentSafety:
    def test_same_file_concurrent(self, tmp_path):
        """같은 파일을 동시에 여러 스레드가 변환 → 모두 고유 파일명 생성"""
        import threading
        outs = []
        lock = threading.Lock()

        def worker():
            out = convert_file(SRC, str(tmp_path), 'JPEG')
            with lock:
                outs.append(out)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(outs) == 5
        assert len(set(outs)) == 5, f"파일명 충돌: {outs}"
        for out in outs:
            assert os.path.exists(out)
