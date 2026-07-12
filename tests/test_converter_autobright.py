"""convert_file 이 auto_bright 를 _open_raw → open_raw_full(bright=) 로 넘기는지 검증."""
from unittest import mock
import core.converter as converter


def test_convert_passes_bright_when_autobright_on():
    with mock.patch("core.converter.open_raw_full") as m:
        converter._open_raw("x.cr2", auto_bright=True)
    assert m.call_args.kwargs.get("bright") == converter.AUTO_BRIGHT_FACTOR


def test_convert_passes_bright_1_when_off():
    with mock.patch("core.converter.open_raw_full") as m:
        converter._open_raw("x.cr2", auto_bright=False)
    assert m.call_args.kwargs.get("bright") == 1.0
