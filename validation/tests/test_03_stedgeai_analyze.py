"""Тест 3: ST Edge AI Core analyze — Flash, RAM, MACC із реального інструменту."""
import pytest

from validation.scripts import config as C


def _need(res, key):
    r = res.get(key, {})
    if r.get("status") != "ok":
        pytest.skip(r.get("reason", "ST Edge AI Core недоступний"))
    return r


@pytest.mark.parametrize("dtype", ["float32", "int8"])
def test_memory_headroom(analyze_result, dtype):
    r = _need(analyze_result, dtype)
    need = 1.0 - C.CRITERIA["memory_headroom_frac"]
    assert r["flash_used_frac"] <= need, (
        f'Flash {r["flash_bytes"]} Б = {r["flash_used_frac"] * 100:.1f} % від '
        f'{C.MCU["flash_kib"]} КіБ, запас менший за '
        f'{C.CRITERIA["memory_headroom_frac"] * 100:.0f} %')
    assert r["ram_used_frac"] <= need, (
        f'RAM {r["ram_bytes"]} Б = {r["ram_used_frac"] * 100:.1f} % від '
        f'{C.MCU["ram_kib"]} КіБ')


def test_macc_matches_analytical_estimate(analyze_result, comparison):
    """Інструмент і мій аналітичний підрахунок мають зійтися в межах 10 %."""
    r = _need(analyze_result, "float32")
    if r.get("macc") is None:
        pytest.skip("у звіті analyze не знайдено MACC")
    mine = comparison["models"][C.CHOSEN]["macc"]
    assert abs(r["macc"] - mine) / mine < 0.10, f'analyze {r["macc"]} проти оцінки {mine}'
