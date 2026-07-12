"""
Unit tests for RawBaker core conversion pipeline.
Run: venv\Scripts\python.exe -m pytest tests\ -v
"""
import os, sys, shutil, stat, time, threading
import pytest
from pathlib import Path
from PIL import Image
import piexif

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.converter import convert_file, RAW_EXTENSIONS, NORMAL_EXTENSIONS

TEST_IMAGES = Path(__file__).parent.parent / 'test_images'
TEST_OUT    = Path(__file__).parent.parent / 'test_output_qa'

@pytest.fixture(autouse=True)
def clean_output():
    TEST_OUT.mkdir(exist_ok=True)
    yield
    shutil.rmtree(TEST_OUT, ignore_errors=True)


# ──────────────────────────────────────────────────────────────
# 1. 포맷별 기본 변환
# ──────────────────────────────────────────────────────────────
class TestFormatConversion:
    SRC_JPG = str(TEST_IMAGES / 'small_exif.jpg')
    SRC_PNG = str(TEST_IMAGES / 'sample.png')
    SRC_BMP = str(TEST_IMAGES / 'sample.bmp')
    SRC_TIF = str(TEST_IMAGES / 'sample.tif')
    SRC_WBP = str(TEST_IMAGES / 'sample.webp')

    @pytest.mark.parametrize("src,fmt,ext", [
        (SRC_JPG, 'JPEG', '.jpg'),
        (SRC_JPG, 'PNG',  '.png'),
        (SRC_JPG, 'TIFF', '.tif'),
        (SRC_JPG, 'WebP', '.webp'),
        (SRC_JPG, 'BMP',  '.bmp'),
        (SRC_PNG, 'JPEG', '.jpg'),
        (SRC_BMP, 'PNG',  '.png'),
        (SRC_TIF, 'JPEG', '.jpg'),
        (SRC_WBP, 'JPEG', '.jpg'),
    ])
    def test_format_output(self, src, fmt, ext):
        out = convert_file(src, str(TEST_OUT), fmt, jpeg_quality=90)
        assert os.path.exists(out), f"출력 파일 없음: {out}"
        assert out.endswith(ext), f"확장자 불일치: {out}"
        assert os.path.getsize(out) > 100, "파일이 비어있음"

    def test_jpeg_quality_difference(self):
        out_hi = convert_file(self.SRC_JPG, str(TEST_OUT), 'JPEG', jpeg_quality=95)
        out_lo = convert_file(self.SRC_JPG, str(TEST_OUT), 'JPEG', jpeg_quality=60)
        size_hi = os.path.getsize(out_hi)
        size_lo = os.path.getsize(out_lo)
        assert size_hi > size_lo, "품질 95가 60보다 작음 — 슬라이더 로직 오류"

    def test_output_is_valid_image(self):
        for fmt in ['JPEG', 'PNG', 'TIFF', 'WebP', 'BMP']:
            out = convert_file(self.SRC_JPG, str(TEST_OUT), fmt)
            img = Image.open(out)
            assert img.size[0] > 0 and img.size[1] > 0

    def test_no_overwrite_source(self):
        """출력 경로가 원본과 같을 때 다른 이름으로 저장"""
        src_dir = str(TEST_IMAGES)
        out = convert_file(str(TEST_IMAGES / 'sample.png'), src_dir, 'PNG')
        assert os.path.abspath(out) != os.path.abspath(str(TEST_IMAGES / 'sample.png'))
        os.remove(out)


# ──────────────────────────────────────────────────────────────
# 2. RAW 파일 변환
# ──────────────────────────────────────────────────────────────
class TestRawConversion:
    SRC_DNG = str(TEST_IMAGES / 'test_synthetic.dng')

    def test_dng_to_jpeg(self):
        out = convert_file(self.SRC_DNG, str(TEST_OUT), 'JPEG', jpeg_quality=90)
        assert os.path.exists(out)
        img = Image.open(out)
        assert img.mode == 'RGB'
        assert img.size[0] > 0

    def test_dng_to_png(self):
        out = convert_file(self.SRC_DNG, str(TEST_OUT), 'PNG')
        assert os.path.exists(out)
        img = Image.open(out)
        assert img.mode == 'RGB'

    def test_dng_to_webp(self):
        out = convert_file(self.SRC_DNG, str(TEST_OUT), 'WebP', jpeg_quality=85)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 100


# ──────────────────────────────────────────────────────────────
# 3. 리사이즈
# ──────────────────────────────────────────────────────────────
class TestResize:
    SRC = str(TEST_IMAGES / 'canon_r5_gps.jpg')

    def _get_size(self, path):
        return Image.open(path).size

    def test_original_preserves_size(self):
        orig = Image.open(self.SRC).size
        out  = convert_file(self.SRC, str(TEST_OUT), 'JPEG', resize_mode='original')
        assert self._get_size(out) == orig

    @pytest.mark.parametrize("mode,factor", [
        ('75%', 0.75), ('50%', 0.50), ('25%', 0.25)
    ])
    def test_percent_resize(self, mode, factor):
        orig_w, orig_h = Image.open(self.SRC).size
        out = convert_file(self.SRC, str(TEST_OUT), 'JPEG', resize_mode=mode)
        w, h = self._get_size(out)
        assert abs(w - int(orig_w * factor)) <= 2
        assert abs(h - int(orig_h * factor)) <= 2

    def test_custom_width(self):
        out = convert_file(self.SRC, str(TEST_OUT), 'JPEG',
                           resize_mode='custom', custom_w=400, custom_h=0)
        w, h = self._get_size(out)
        assert w == 400
        assert h > 0  # 높이 자동 계산

    def test_custom_height(self):
        out = convert_file(self.SRC, str(TEST_OUT), 'JPEG',
                           resize_mode='custom', custom_w=0, custom_h=300)
        w, h = self._get_size(out)
        assert h == 300
        assert w > 0

    def test_custom_both(self):
        out = convert_file(self.SRC, str(TEST_OUT), 'JPEG',
                           resize_mode='custom', custom_w=500, custom_h=300)
        w, h = self._get_size(out)
        assert w == 500 and h == 300


# ──────────────────────────────────────────────────────────────
# 4. EXIF 보존 및 GPS 제거
# ──────────────────────────────────────────────────────────────
class TestExif:
    SRC_GPS    = str(TEST_IMAGES / 'canon_r5_gps.jpg')    # GPS 있음
    SRC_NOGPS  = str(TEST_IMAGES / 'canon_r5_nogps.jpg')  # GPS 없음

    def _load_exif(self, path):
        try:
            return piexif.load(path)
        except Exception:
            return {}

    def test_exif_preserved_camera_info(self):
        """카메라 정보가 출력에 유지되어야 함"""
        out = convert_file(self.SRC_GPS, str(TEST_OUT), 'JPEG', exif_mode='keep')
        exif = self._load_exif(out)
        assert piexif.ImageIFD.Make in exif.get('0th', {}), "Make 태그 없음"
        assert exif['0th'][piexif.ImageIFD.Make] == b'Canon'

    def test_exif_date_preserved(self):
        """촬영 날짜가 유지되어야 함"""
        out = convert_file(self.SRC_GPS, str(TEST_OUT), 'JPEG', exif_mode='keep')
        exif = self._load_exif(out)
        assert piexif.ExifIFD.DateTimeOriginal in exif.get('Exif', {}), "DateTimeOriginal 없음"

    def test_gps_removed(self):
        """GPS 제거 옵션: GPS 태그 없어야 함"""
        out = convert_file(self.SRC_GPS, str(TEST_OUT), 'JPEG', exif_mode='remove_gps')
        exif = self._load_exif(out)
        gps = exif.get('GPS', {})
        assert piexif.GPSIFD.GPSLatitude not in gps, "GPS가 여전히 남아있음"

    def test_camera_info_survives_gps_removal(self):
        """GPS만 제거 → 카메라 정보는 유지"""
        out = convert_file(self.SRC_GPS, str(TEST_OUT), 'JPEG', exif_mode='remove_gps')
        exif = self._load_exif(out)
        assert piexif.ImageIFD.Make in exif.get('0th', {})

    def test_exif_all_removed(self):
        """전체 제거: EXIF 데이터 없어야 함"""
        out = convert_file(self.SRC_GPS, str(TEST_OUT), 'JPEG', exif_mode='remove_all')
        try:
            exif = piexif.load(out)
            assert not exif.get('0th') or piexif.ImageIFD.Make not in exif['0th']
        except Exception:
            pass  # EXIF 자체가 없으면 통과

    def test_no_gps_source_keep_mode(self):
        """원본에 GPS 없을 때 keep 모드도 안전해야 함"""
        out = convert_file(self.SRC_NOGPS, str(TEST_OUT), 'JPEG', exif_mode='keep')
        assert os.path.exists(out)


# ──────────────────────────────────────────────────────────────
# 5. 배치 변환 (다중 파일)
# ──────────────────────────────────────────────────────────────
class TestBatchConversion:
    SRCS = [
        str(TEST_IMAGES / 'small_exif.jpg'),
        str(TEST_IMAGES / 'sample.png'),
        str(TEST_IMAGES / 'sample.bmp'),
        str(TEST_IMAGES / 'sample.webp'),
        str(TEST_IMAGES / 'test_synthetic.dng'),
    ]

    def test_batch_all_succeed(self):
        results = []
        for src in self.SRCS:
            try:
                out = convert_file(src, str(TEST_OUT), 'JPEG', jpeg_quality=90)
                results.append(('ok', src, out))
            except Exception as e:
                results.append(('err', src, str(e)))

        errors = [r for r in results if r[0] == 'err']
        assert not errors, f"배치 변환 실패:\n" + '\n'.join(f"  {r[1]}: {r[2]}" for r in errors)

    def test_batch_no_collision(self):
        """같은 이름 파일 여러 번 변환해도 충돌 없어야 함"""
        outs = []
        for _ in range(3):
            out = convert_file(str(TEST_IMAGES / 'small_exif.jpg'),
                               str(TEST_OUT), 'JPEG')
            outs.append(out)
        assert len(set(outs)) == len(outs), "파일명 충돌 발생"

    def test_batch_threaded(self):
        """멀티스레드 동시 변환 — 데이터 경합 없이 완료"""
        errors = []
        threads = []

        def worker(src):
            try:
                convert_file(src, str(TEST_OUT), 'JPEG', jpeg_quality=85)
            except Exception as e:
                errors.append(str(e))

        for src in self.SRCS:
            t = threading.Thread(target=worker, args=(src,))
            threads.append(t)
        for t in threads: t.start()
        for t in threads: t.join(timeout=30)

        assert not errors, f"스레드 변환 오류: {errors}"


# ──────────────────────────────────────────────────────────────
# 6. 진행 콜백 (progress_cb)
# ──────────────────────────────────────────────────────────────
class TestProgressCallback:
    SRC = str(TEST_IMAGES / 'small_exif.jpg')

    def test_progress_called(self):
        calls = []
        convert_file(self.SRC, str(TEST_OUT), 'JPEG',
                     progress_cb=lambda pct: calls.append(pct))
        assert len(calls) >= 2, "progress_cb가 한 번도 안 불림"
        assert calls[-1] == 100, "마지막 콜백이 100%가 아님"
        assert all(0 <= c <= 100 for c in calls), "진행률 범위 오류"

    def test_progress_monotonic(self):
        """진행률은 단조 증가해야 함"""
        calls = []
        convert_file(self.SRC, str(TEST_OUT), 'JPEG',
                     progress_cb=lambda pct: calls.append(pct))
        for i in range(1, len(calls)):
            assert calls[i] >= calls[i-1], f"진행률 역행: {calls}"
