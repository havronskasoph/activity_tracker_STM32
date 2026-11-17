"""Спільні фікстури: беруть готові results/*.json, а якщо їх немає — рахують на льоту."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from validation.scripts import config as C          # noqa: E402
from validation.scripts import quantize, stedgeai, steps  # noqa: E402


def _cached(name: str, compute):
    p = C.RESULTS_DIR / name
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    data = compute()
    C.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


@pytest.fixture(scope="session")
def comparison():
    return _cached("01_model_comparison.json", steps.step_model_comparison)


@pytest.fixture(scope="session")
def quantization(comparison):
    return _cached("02_quantization.json",
                   lambda: quantize.run(comparison["models"][C.CHOSEN]["test"]))


@pytest.fixture(scope="session")
def analyze_result():
    def compute():
        tfl = C.RESULTS_DIR / f"{C.MODELS[C.CHOSEN]['name']}_int8.tflite"
        out = {"float32": stedgeai.analyze(C.MODELS[C.CHOSEN]["dir"] / "model.keras", "f32")}
        out["int8"] = (stedgeai.analyze(tfl, "int8") if tfl.exists()
                       else {"status": "skipped", "reason": "немає int8-моделі"})
        return out
    return _cached("03_stedgeai_analyze.json", compute)


@pytest.fixture(scope="session")
def validate_result():
    def compute():
        tfl = C.RESULTS_DIR / f"{C.MODELS[C.CHOSEN]['name']}_int8.tflite"
        target = tfl if tfl.exists() else C.MODELS[C.CHOSEN]["dir"] / "model.keras"
        return stedgeai.validate(target, "val")
    return _cached("04_stedgeai_validate.json", compute)


@pytest.fixture(scope="session")
def parity():
    return _cached("05_preprocessing_parity.json", steps.step_preprocessing_parity)


@pytest.fixture(scope="session")
def vectors():
    return _cached("06_test_vectors.json", steps.step_test_vectors)
