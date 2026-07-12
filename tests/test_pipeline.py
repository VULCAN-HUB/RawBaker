"""Pipeline architecture tests."""
import sys, os
import pytest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.pipeline import (
    ImagePipeline, ResizeStep, ColorModeStep, build_pipeline, ImageStep,
    ExposureStep, BrightnessStep, ContrastStep, GammaStep,
    WhitesStep, BlacksStep, HighlightsStep, ShadowsStep,
    WhiteBalanceStep, TintStep, VibranceStep, SaturationStep, HueStep,
    ClarityStep, SharpnessStep, DenoiseStep,
    VignetteStep, GrainStep, apply_adjustments,
)
from core.converter import convert_file

TEST_IMAGES = Path(__file__).parent.parent / 'test_images'
TEST_OUT    = Path(__file__).parent.parent / 'test_output_pipeline'


@pytest.fixture(autouse=True)
def clean():
    import shutil
    TEST_OUT.mkdir(exist_ok=True)
    yield
    shutil.rmtree(TEST_OUT, ignore_errors=True)


class TestPipelineStructure:
    def test_empty_pipeline_passthrough(self):
        img = Image.new('RGB', (100, 100), (200, 100, 50))
        result = ImagePipeline().run(img)
        assert result.size == img.size

    def test_steps_execute_in_order(self):
        """ResizeStep 후 ColorModeStep — 순서 보장 확인"""
        img = Image.new('RGBA', (800, 600))
        pipeline = (ImagePipeline()
                    .add_step(ResizeStep('50%'))
                    .add_step(ColorModeStep('JPEG')))
        result = pipeline.run(img)
        assert result.size == (400, 300)
        assert result.mode == 'RGB'

    def test_repr(self):
        p = build_pipeline('JPEG', '50%')
        assert 'ResizeStep' in repr(p)
        assert 'ColorModeStep' in repr(p)

    def test_add_step_chaining(self):
        p = ImagePipeline()
        ret = p.add_step(ResizeStep('original'))
        assert ret is p   # 체이닝 지원 확인

    def test_insert_before(self):
        """보정 단계를 리사이즈 앞에 끼워 넣기"""
        class NoopStep(ImageStep):
            def apply(self, img): return img

        p = build_pipeline('JPEG', '50%')
        p.insert_before(ResizeStep, NoopStep())
        assert isinstance(p._steps[0], NoopStep)
        assert isinstance(p._steps[1], ResizeStep)

    def test_progress_callback_range(self):
        img = Image.new('RGB', (200, 200))
        p = build_pipeline('JPEG', '50%')
        calls = []
        p.run(img, progress_cb=lambda pct: calls.append(pct))
        assert all(30 <= c <= 80 for c in calls)


class TestPipelineWithConverter:
    SRC = str(TEST_IMAGES / 'small_exif.jpg')

    def test_custom_pipeline_passed_to_converter(self):
        """파이프라인을 직접 주입하면 해당 파이프라인이 실행됨"""
        custom = build_pipeline('PNG', '25%')
        out = convert_file(self.SRC, str(TEST_OUT), 'PNG', pipeline=custom)
        img = Image.open(out)
        orig = Image.open(self.SRC)
        assert abs(img.size[0] - orig.size[0] * 0.25) <= 2

    def test_default_pipeline_created_automatically(self):
        """pipeline=None 이면 기본 파이프라인 자동 생성"""
        out = convert_file(self.SRC, str(TEST_OUT), 'JPEG',
                           resize_mode='50%', pipeline=None)
        img = Image.open(out)
        orig = Image.open(self.SRC)
        assert abs(img.size[0] - orig.size[0] * 0.5) <= 2

    def test_phase2_brightness_applies(self):
        """BrightnessStep이 이미지를 실제로 변환한다."""
        img = Image.new('RGB', (100, 100), (100, 100, 100))
        result = BrightnessStep(factor=2.0).apply(img)
        assert result.size == img.size
        assert result.getpixel((50, 50))[0] > 100  # 더 밝아야 함

    def test_all_18_steps_pipeline(self):
        """18개 보정 Step 전부 파이프라인에 생성된다."""
        adj = {
            "exposure": 1.0, "gamma": 30.0, "whites": 20.0, "blacks": -20.0,
            "highlights": 30.0, "shadows": -20.0, "brightness": 1.2, "contrast": 1.1,
            "white_balance": 20, "tint": 10, "vibrance": 25.0, "saturation": 0.8,
            "hue": 15.0, "clarity": 30.0, "sharpness": 50.0, "denoise": 20.0,
            "vignette": 40.0, "grain": 15.0,
        }
        p = build_pipeline("JPEG", adjustments=adj)
        step_types = [type(s) for s in p._steps]
        for cls in [ExposureStep, GammaStep, WhitesStep, BlacksStep,
                    HighlightsStep, ShadowsStep, BrightnessStep, ContrastStep,
                    WhiteBalanceStep, TintStep, VibranceStep, SaturationStep,
                    HueStep, ClarityStep, SharpnessStep, DenoiseStep,
                    VignetteStep, GrainStep]:
            assert cls in step_types, f"{cls.__name__} missing"

    def test_all_new_steps_apply(self):
        """새 보정 Step들이 이미지를 변형한다."""
        img = Image.new("RGB", (100, 100), (128, 128, 128))
        assert GammaStep(50.0).apply(img).getpixel((50,50))[0] > 128
        assert GammaStep(-50.0).apply(img).getpixel((50,50))[0] < 128
        assert WhitesStep(50.0).apply(img).size == (100, 100)
        assert BlacksStep(-50.0).apply(img).size == (100, 100)
        assert TintStep(30).apply(img).size == (100, 100)
        assert VibranceStep(50.0).apply(img).size == (100, 100)
        assert ClarityStep(50.0).apply(img).size == (100, 100)
        assert DenoiseStep(50.0).apply(img).size == (100, 100)
        assert GrainStep(30.0).apply(img).size == (100, 100)
        result_adj = apply_adjustments(img, {"gamma": 30.0, "vibrance": 20.0, "grain": 10.0})
        assert result_adj.size == (100, 100)
