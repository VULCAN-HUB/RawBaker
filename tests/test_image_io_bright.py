"""open_raw_full / open_raw_preview 의 bright 인자 시그니처 검증.

실제 RAW 디코딩(rawpy)은 무겁고 테스트 RAW가 없으므로,
rawpy.imread 를 가짜로 패치해 postprocess 가 받는 bright 값만 확인한다.
"""
import sys
import types
import numpy as np
from unittest import mock

import core.image_io as image_io


class _FakeRaw:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def postprocess(self, **kwargs):
        _FakeRaw.last_kwargs = kwargs
        return np.zeros((4, 4, 3), dtype=np.uint8)


def _patch_rawpy():
    fake = types.ModuleType("rawpy")
    fake.imread = lambda path: _FakeRaw()
    class _CS:
        sRGB = 1
    fake.ColorSpace = _CS
    return mock.patch.dict(sys.modules, {"rawpy": fake})


def test_open_raw_full_default_bright_is_boost():
    with _patch_rawpy():
        image_io.open_raw_full("dummy.cr2")
    assert _FakeRaw.last_kwargs["bright"] == image_io.AUTO_BRIGHT_FACTOR


def test_open_raw_full_bright_off():
    with _patch_rawpy():
        image_io.open_raw_full("dummy.cr2", bright=1.0)
    assert _FakeRaw.last_kwargs["bright"] == 1.0


def test_open_raw_preview_accepts_bright():
    with _patch_rawpy():
        image_io.open_raw_preview("dummy.cr2", bright=1.0)
    assert _FakeRaw.last_kwargs["bright"] == 1.0
    assert _FakeRaw.last_kwargs["half_size"] is True


def test_open_raw_preview_default_bright_is_boost():
    with _patch_rawpy():
        image_io.open_raw_preview("dummy.cr2")
    assert _FakeRaw.last_kwargs["bright"] == image_io.AUTO_BRIGHT_FACTOR
