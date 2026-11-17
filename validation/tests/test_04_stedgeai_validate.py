"""Тест 4: ST Edge AI Core validate — C-модель проти оригіналу."""
import pytest

from validation.scripts import config as C


def _need(v):
    if v.get("status") != "ok":
        pytest.skip(v.get("reason", "ST Edge AI Core недоступний"))


def test_argmax_fully_matches(validate_result):
    _need(validate_result)
    if "argmax_match" not in validate_result:
        pytest.skip("у звіті validate не знайдено частку збігів")
    need = C.CRITERIA["validate_argmax_match"]
    assert validate_result["argmax_match"] >= need, (
        f'збіг argmax {validate_result["argmax_match"] * 100:.2f} % < {need * 100:.0f} %')
