"""Тести 3 і 4: ST Edge AI Core analyze і validate.

Інструмент треба встановити окремо (потрібен акаунт ST) — див. validation/README.md.
Якщо його немає, обидва тести повертають "skipped" із причиною, і pytest робить SKIP.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import config as C

TARGET = "stm32u5"


def available() -> tuple[bool, str]:
    exe = shutil.which(C.STEDGEAI) or (Path(C.STEDGEAI).exists() and C.STEDGEAI)
    if not exe:
        return False, ("ST Edge AI Core не знайдено. Встанови його і або додай у PATH, "
                       "або задай змінну STEDGEAI_PATH з повним шляхом до stedgeai(.exe). "
                       "Інструкція — у validation/README.md.")
    return True, ""


def _run(args: list[str], cwd: Path) -> tuple[int, str]:
    exe = shutil.which(C.STEDGEAI) or C.STEDGEAI
    try:
        p = subprocess.run([exe, *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=900)
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


_NUM = r"([\d\s,.]+)"


def _grab(text: str, *patterns: str) -> int | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(" ", "").replace(",", "")
            try:
                return int(float(raw))
            except ValueError:
                continue
    return None


def analyze(model_path: Path, tag: str) -> dict:
    ok, why = available()
    if not ok:
        return {"status": "skipped", "reason": why}
    out_dir = C.VALIDATION_DIR / "stedgeai_out" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    code, text = _run(["analyze", "--model", str(model_path), "--target", TARGET,
                       "--workspace", str(out_dir / "ws"), "--output", str(out_dir)],
                      C.VALIDATION_DIR)
    (out_dir / "analyze.log").write_text(text, encoding="utf-8")
    if code != 0:
        return {"status": "error", "returncode": code, "log": str(out_dir / "analyze.log")}

    flash = _grab(text, r"weights.*?:\s*" + _NUM + r"\s*B", r"ROM.*?:\s*" + _NUM + r"\s*B")
    ram = _grab(text, r"activations.*?:\s*" + _NUM + r"\s*B", r"RAM.*?:\s*" + _NUM + r"\s*B")
    macc = _grab(text, r"MACC.*?:\s*" + _NUM)
    res = {"status": "ok", "model": model_path.name, "target": TARGET,
           "flash_bytes": flash, "ram_bytes": ram, "macc": macc,
           "log": str(out_dir / "analyze.log")}
    if flash is not None and ram is not None:
        res["flash_used_frac"] = flash / (C.MCU["flash_kib"] * 1024)
        res["ram_used_frac"] = ram / (C.MCU["ram_kib"] * 1024)
        need = 1.0 - C.CRITERIA["memory_headroom_frac"]
        res["passed"] = bool(res["flash_used_frac"] <= need and res["ram_used_frac"] <= need)
    return res


def validate(model_path: Path, tag: str) -> dict:
    ok, why = available()
    if not ok:
        return {"status": "skipped", "reason": why}
    out_dir = C.VALIDATION_DIR / "stedgeai_out" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    code, text = _run(["validate", "--model", str(model_path), "--target", TARGET,
                       "--mode", "host", "--workspace", str(out_dir / "ws_val"),
                       "--output", str(out_dir)], C.VALIDATION_DIR)
    (out_dir / "validate.log").write_text(text, encoding="utf-8")
    if code != 0:
        return {"status": "error", "returncode": code, "log": str(out_dir / "validate.log")}
    acc = re.search(r"acc=([\d.]+)%", text)
    l2r = re.search(r"l2r\s+([\d.e+-]+)", text, re.IGNORECASE)
    res = {"status": "ok", "model": model_path.name, "mode": "host",
           "log": str(out_dir / "validate.log")}
    if acc:
        res["argmax_match"] = float(acc.group(1)) / 100.0
        res["passed"] = bool(res["argmax_match"] >= C.CRITERIA["validate_argmax_match"])
    if l2r:
        res["l2_rel_error"] = float(l2r.group(1))
    return res
