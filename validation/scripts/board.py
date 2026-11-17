"""Тести на платі: фактичний ODR, час інференсу, прогін тестових векторів, живий лог.

Прошивка друкує все потрібне рядками з '#':
    # selftest match=<n>/<N>
    # selftest cycles min=.. avg=.. max=.. clk=..
    # selftest us avg=..
    # rate=<Гц> windows=<n> missed=<n>
    # pred t=<мс> class=<назва> p=<імовірність>

Якщо плата не підключена, capture() повертає None і pytest робить SKIP.
Збережені логи в board_logs/ дозволяють перерахувати результати без плати.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

from . import config as C

BAUD = 115200
LOGS_DIR = C.VALIDATION_DIR / "board_logs"


def find_port() -> str | None:
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for p in list_ports.comports():
        if "STLink" in (p.description or "") or "ST-Link" in (p.description or ""):
            return p.device
    return None


def capture(seconds: float = 25.0, port: str | None = None) -> str | None:
    """Читає UART плати. None, якщо плати немає або pyserial не встановлений."""
    try:
        import serial
    except ImportError:
        return None
    port = port or find_port()
    if not port:
        return None
    try:
        ser = serial.Serial(port, BAUD, timeout=0.3)
    except Exception:
        return None
    out, t0 = [], time.monotonic()
    while time.monotonic() - t0 < seconds:
        b = ser.readline()
        if b:
            out.append(b.decode("utf-8", "replace"))
    ser.close()
    return "".join(out)


def parse(text: str) -> dict:
    """Розбирає лог плати на показники."""
    res: dict = {"lines": len(text.splitlines())}
    m = re.search(r"# selftest match=(\d+)/(\d+)", text)
    if m:
        ok, total = int(m.group(1)), int(m.group(2))
        res["vectors"] = {"matched": ok, "total": total, "ratio": ok / total}
    m = re.search(r"# selftest cycles min=(\d+) avg=(\d+) max=(\d+) clk=(\d+)", text)
    if m:
        mn, avg, mx, clk = (int(m.group(i)) for i in range(1, 5))
        res["inference"] = {
            "cycles_min": mn, "cycles_avg": avg, "cycles_max": mx, "clock_hz": clk,
            "ms_min": mn * 1000.0 / clk, "ms_avg": avg * 1000.0 / clk,
            "ms_max": mx * 1000.0 / clk,
        }
    rates = [(float(a), int(b), int(c)) for a, b, c in
             re.findall(r"# rate=([\d.]+) Hz windows=(\d+) missed=(\d+)", text)]
    if len(rates) >= 2:
        processed = float(np.mean([r[0] for r in rates[1:]]))
        dropped = (rates[-1][2] - rates[0][2]) / ((len(rates) - 1) * 5.0)
        actual = processed + dropped
        res["odr"] = {
            "processed_hz": processed, "dropped_per_s": dropped, "actual_hz": actual,
            "nominal_hz": C.BOARD["fs_hz"],
            "deviation_pct": (actual / C.BOARD["fs_hz"] - 1) * 100,
            "window_seconds": C.BOARD["window_samples"] / actual,
            "status_lines": len(rates),
        }
    preds = re.findall(r"# pred t=(\d+) class=(\w+) p=([\d.]+)", text)
    if preds:
        t = np.array([int(p[0]) for p in preds])
        res["live"] = {
            "count": len(preds),
            "classes": dict(Counter(p[1] for p in preds)),
            "p_min": min(float(p[2]) for p in preds),
            "p_max": max(float(p[2]) for p in preds),
            "period_ms_median": float(np.median(np.diff(t))) if len(t) > 1 else None,
        }
    return res


def from_log(name: str) -> dict | None:
    p = LOGS_DIR / name
    if not p.exists():
        return None
    return parse(p.read_text(encoding="utf-8", errors="replace"))


def collect(live_seconds: float = 25.0, prefer_live: bool = True) -> dict:
    """Збирає всі показники плати.

    Спершу пробує зняти з живої плати; якщо її немає — бере збережені логи
    з board_logs/, щоб результати можна було перерахувати будь-де.
    """
    out: dict = {}
    text = capture(live_seconds) if prefer_live else None
    if text and "# selftest" in text:
        out["source"] = "live"
        out.update(parse(text))
    else:
        rel = from_log("selftest_release.log")
        if rel is None:
            return {"status": "skipped",
                    "reason": "плата не підключена і немає board_logs/selftest_release.log"}
        out["source"] = "board_logs/selftest_release.log"
        out.update(rel)
        if "odr" not in out:
            dbg = from_log("stream_debug.log")
            if dbg and "odr" in dbg:
                out["odr"] = dbg["odr"]
                out["odr"]["source"] = "board_logs/stream_debug.log"
    out["status"] = "ok"
    out["build"] = "Release (-Os)" if out.get("source", "").endswith("release.log") else "live"
    return out


def split_results(data: dict) -> dict[str, dict]:
    """Розкладає зібране по файлах board_*.json із критеріями й вердиктом."""
    files: dict[str, dict] = {}
    if "odr" in data:
        o = dict(data["odr"])
        tol = 2.0
        o["criterion"] = f"{C.BOARD['fs_hz']:g} Гц ± {tol:g} %"
        o["passed"] = abs(o["deviation_pct"]) <= tol
        o["status"] = "ok"
        files["board_odr.json"] = o
    if "inference" in data:
        i = dict(data["inference"])
        hop_s = C.BOARD["hop_samples"] / C.BOARD["fs_hz"]
        i["hop_budget_ms"] = hop_s * 1000
        i["budget_used_frac"] = i["ms_avg"] / (hop_s * 1000)
        i["criterion"] = "істотно менше кроку вікна"
        i["passed"] = i["ms_avg"] < 0.5 * hop_s * 1000
        i["build"] = data.get("build")
        i["status"] = "ok"
        files["board_inference.json"] = i
    if "vectors" in data:
        v = dict(data["vectors"])
        v["criterion"] = C.CRITERIA["board_argmax_match"]
        v["passed"] = v["ratio"] >= C.CRITERIA["board_argmax_match"]
        v["status"] = "ok"
        files["board_vectors.json"] = v
    if "live" in data:
        l = dict(data["live"])
        l["criterion"] = "модель видає клас у реальному часі"
        l["passed"] = l["count"] > 0
        l["status"] = "ok"
        files["board_live.json"] = l
    return files
