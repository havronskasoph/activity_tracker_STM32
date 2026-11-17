"""Тест 2: квантування int8 (PTQ) проти float32."""
import pytest

from validation.scripts import config as C


def _need(q):
    if q.get("status") != "ok":
        pytest.skip(q.get("reason", "квантування не виконувалось"))


def test_macro_f1_drop_within_limit(quantization):
    _need(quantization)
    limit = C.CRITERIA["quant_macro_f1_drop_pp"]
    assert quantization["macro_f1_drop_pp"] <= limit, (
        f'падіння macro-F1 {quantization["macro_f1_drop_pp"]:.2f} п. > {limit} п.')


def test_walking_f1_drop_within_limit(quantization):
    """Walking — найслабший клас, саме його квантування може добити."""
    _need(quantization)
    limit = C.CRITERIA["quant_walking_drop_pp"]
    assert quantization["walking_f1_drop_pp"] <= limit, (
        f'падіння F1 Walking {quantization["walking_f1_drop_pp"]:.2f} п. > {limit} п.')


def test_int8_model_is_smaller_than_float(quantization, comparison):
    _need(quantization)
    assert quantization["tflite_bytes"] < comparison["models"][C.CHOSEN]["weights_bytes_f32"]


def test_no_class_collapsed(quantization):
    """Жоден клас не має провалитися в нуль: це означало б зламане квантування."""
    _need(quantization)
    for cls, f1 in quantization["int8"]["f1_per_class"].items():
        assert f1 > 0.0, f"клас {cls} після квантування має F1 = 0"
