"""Тест 6: тестові вектори для звірки ПК і MCU.

Сам прогін на платі — ручний крок (див. test_vectors/README.md). Тут
перевіряється, що вектори згенеровані правильно й самоузгоджені.
"""
import numpy as np

from validation.scripts import config as C


def test_counts(vectors):
    assert vectors["n_vectors"] == C.CRITERIA["vectors_per_class"] * len(C.CLASS_NAMES)
    for cls, n in vectors["class_distribution"].items():
        assert n == C.CRITERIA["vectors_per_class"], f"{cls}: {n} вікон"


def test_window_shape_matches_board(vectors):
    assert vectors["window_shape"] == [C.BOARD["window_samples"], C.BOARD["channels"]]


def test_files_exist_and_are_small(vectors):
    for name, size in vectors["files"].items():
        p = C.VECTORS_DIR / name
        assert p.exists(), name
        assert size < 5 * 1024 * 1024, f"{name}: {size} Б — завеликий для репозиторію"


def test_npz_contents_consistent(vectors):
    d = np.load(C.VECTORS_DIR / "test_vectors.npz")
    x = d["x_normalized"]
    assert x.shape == (vectors["n_vectors"], C.BOARD["window_samples"], C.BOARD["channels"])
    assert x.dtype == np.float32
    assert np.isfinite(x).all()
    assert (d["proba"].argmax(1) == d["y_pred"]).all()
    assert np.allclose(d["proba"].sum(1), 1.0, atol=1e-5)


def test_c_header_declares_matching_sizes(vectors):
    text = (C.VECTORS_DIR / "har_test_vectors.h").read_text(encoding="utf-8")
    assert f'#define HAR_TV_COUNT   {vectors["n_vectors"]}' in text
    assert f'#define HAR_TV_SAMPLES {C.BOARD["window_samples"]}' in text
    assert f'#define HAR_TV_CHANNELS {C.BOARD["channels"]}' in text


def test_expected_csv_rows(vectors):
    rows = (C.VECTORS_DIR / "expected.csv").read_text(encoding="utf-8").strip().split("\n")
    assert len(rows) == vectors["n_vectors"] + 1
