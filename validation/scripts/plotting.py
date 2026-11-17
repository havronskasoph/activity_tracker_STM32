"""Графіки для презентації. Єдиний стиль, dpi 150, підписи українською.

Палітра — слоти 1-3 валідованого категорійного набору (validate_palette.js,
light, --pairs all: усі перевірки пройдено). Колір закріплений за моделлю й не
змінюється між графіками. Аквамариновий слот має контраст нижче 3:1 до полотна,
тому всі стовпці несуть прямі підписи значень (правило компенсації).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from . import config as C

plt.rcParams.update({
    "figure.facecolor": C.SURFACE,
    "axes.facecolor": C.SURFACE,
    "savefig.facecolor": C.SURFACE,
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.labelsize": 10,
    "axes.labelcolor": C.INK_MUTED,
    "axes.edgecolor": C.GRID,
    "axes.linewidth": 0.8,
    "text.color": C.INK,
    "xtick.color": C.INK_MUTED,
    "ytick.color": C.INK_MUTED,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.frameon": False,
    "legend.fontsize": 9,
    "grid.color": C.GRID,
    "grid.linewidth": 0.7,
    "figure.dpi": C.DPI,
    "savefig.dpi": C.DPI,
    "savefig.bbox": "tight",
})

SEQ = LinearSegmentedColormap.from_list("har_seq", ["#f4f7fb", "#2a78d6", "#10325c"])


def _finish(ax, title: str, ylabel: str = "", ymax: float | None = None):
    ax.set_title(title, color=C.INK, pad=12, loc="left")
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True)
    ax.xaxis.grid(False)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if ymax is not None:
        ax.set_ylim(0, ymax)


def _save(fig, name: str) -> Path:
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    p = C.FIGURES_DIR / name
    fig.savefig(p)
    plt.close(fig)
    return p


def _bars(ax, groups, series, values, colors, labels, fmt="{:.3f}", rot=0):
    """groups: підписи по осі X; series: ключі; values[s][g]."""
    n = len(series)
    width = 0.8 / n
    x = np.arange(len(groups))
    for i, s in enumerate(series):
        off = (i - (n - 1) / 2) * width
        # 2px проміжок між сусідніми стовпцями дає сама ширина (0.8/n з зазором)
        b = ax.bar(x + off, values[s], width * 0.88, color=colors[s], label=labels[s],
                   linewidth=0)
        ax.bar_label(b, fmt=fmt, padding=2, fontsize=7.5, color=C.INK_MUTED)
    ax.set_xticks(x, groups, rotation=rot, ha="right" if rot else "center")


# ── 1. macro-F1 трьох моделей ────────────────────────────────────────────────
def models_macro_f1(cmp: dict) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    groups = ["val", "test"]
    vals = {k: [cmp["models"][k]["val"]["macro_f1"], cmp["models"][k]["test"]["macro_f1"]]
            for k in C.MODEL_ORDER}
    labels = {k: cmp["models"][k]["label"] for k in C.MODEL_ORDER}
    _bars(ax, groups, C.MODEL_ORDER, vals, C.SERIES, labels)
    _finish(ax, "macro-F1 трьох моделей", "macro-F1", 1.0)
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    return _save(fig, "models_macro_f1.png")


# ── 2. F1 по класах ──────────────────────────────────────────────────────────
def models_f1_per_class(cmp: dict) -> Path:
    fig, ax = plt.subplots(figsize=(9, 4.4))
    vals = {k: [cmp["models"][k]["test"]["f1_per_class"][c] for c in C.CLASS_NAMES]
            for k in C.MODEL_ORDER}
    labels = {k: cmp["models"][k]["label"] for k in C.MODEL_ORDER}
    _bars(ax, C.CLASS_NAMES, C.MODEL_ORDER, vals, C.SERIES, labels)
    _finish(ax, "F1 по класах на test", "F1", 1.08)
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    ax.annotate("Walking — найслабший клас у всіх трьох",
                xy=(2, 0.54), xytext=(2, 0.80), fontsize=8.5, color=C.INK_MUTED,
                ha="center",
                arrowprops=dict(arrowstyle="->", color=C.INK_MUTED, lw=0.9,
                                shrinkA=2, shrinkB=4))
    return _save(fig, "models_f1_per_class.png")


# ── 3. Точність проти обчислювальної вартості ────────────────────────────────
def f1_vs_macc(cmp: dict) -> Path:
    fig, ax = plt.subplots(figsize=(7, 4.4))
    for k in C.MODEL_ORDER:
        m = cmp["models"][k]
        chosen = k == C.CHOSEN
        ax.scatter(m["macc"] / 1000, m["test"]["macro_f1"], s=190 if chosen else 120,
                   color=C.SERIES[k], zorder=3, edgecolor=C.SURFACE, linewidth=2,
                   marker="D" if chosen else "o")
        note = f'{m["label"]}\n{m["params"]:,} парам.'.replace(",", " ")
        ax.annotate(note + ("\n(обрана)" if chosen else ""),
                    (m["macc"] / 1000, m["test"]["macro_f1"]),
                    textcoords="offset points", xytext=(12, -4),
                    fontsize=8.5, color=C.INK)
    ax.set_xlabel("обчислення на одне вікно, тис. MACC")
    _finish(ax, "Точність проти обчислювальної вартості", "macro-F1 на test")
    ax.set_xlim(0, max(cmp["models"][k]["macc"] for k in C.MODEL_ORDER) / 1000 * 1.35)
    lo = min(cmp["models"][k]["test"]["macro_f1"] for k in C.MODEL_ORDER)
    hi = max(cmp["models"][k]["test"]["macro_f1"] for k in C.MODEL_ORDER)
    ax.set_ylim(lo - 0.03, hi + 0.02)
    return _save(fig, "f1_vs_macc.png")


# ── 4. Матриця помилок обраної моделі ────────────────────────────────────────
def confusion_chosen(cmp: dict) -> Path:
    m = cmp["models"][C.CHOSEN]
    cm = np.asarray(m["test"]["confusion_matrix"], dtype=float)
    norm = cm / cm.sum(axis=1, keepdims=True) * 100
    fig, ax = plt.subplots(figsize=(6.4, 5.4))
    im = ax.imshow(norm, cmap=SEQ, vmin=0, vmax=100)
    ax.set_xticks(range(5), C.CLASS_NAMES, rotation=35, ha="right")
    ax.set_yticks(range(5), C.CLASS_NAMES)
    ax.set_xlabel("передбачено")
    ax.set_ylabel("істина")
    for i in range(5):
        for j in range(5):
            ax.text(j, i, f"{norm[i, j]:.0f}", ha="center", va="center", fontsize=9,
                    color="white" if norm[i, j] > 55 else C.INK)
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cb.set_label("% від класу (recall)", color=C.INK_MUTED)
    cb.outline.set_visible(False)
    ax.set_title(f'Матриця помилок: {m["label"]}, test', color=C.INK, loc="left", pad=12)
    for s in ax.spines.values():
        s.set_visible(False)
    return _save(fig, "confusion_104hz.png")


# ── 5. macro-F1 по учасниках ─────────────────────────────────────────────────
def f1_per_subject(cmp: dict) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    subs = [str(s) for s in C.TEST_SUBJECTS]
    vals = {k: [cmp["models"][k]["test"]["per_subject"][s]["macro_f1"] for s in subs]
            for k in C.MODEL_ORDER}
    labels = {k: cmp["models"][k]["label"] for k in C.MODEL_ORDER}
    _bars(ax, [f"учасник {s}" for s in subs], C.MODEL_ORDER, vals, C.SERIES, labels)
    _finish(ax, "macro-F1 по учасниках test", "macro-F1", 1.0)
    ax.legend(ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    return _save(fig, "f1_per_subject.png")


# ── 6. float32 проти int8 ────────────────────────────────────────────────────
def float_vs_int8(q: dict) -> Path:
    fig, ax = plt.subplots(figsize=(8.4, 4.4))
    if q.get("status") != "ok":
        ax.axis("off")
        ax.text(0.5, 0.5, "Тест квантування не виконувався\n\n" + q.get("reason", ""),
                ha="center", va="center", fontsize=11, color=C.INK_MUTED, wrap=True)
        ax.set_title("float32 проти int8", color=C.INK, loc="left")
        return _save(fig, "float_vs_int8.png")
    series = ["float32", "int8"]
    colors = {"float32": C.SERIES["104hz"], "int8": C.SERIES["52hz"]}
    vals = {s: [q[{"float32": "float32", "int8": "int8"}[s]]["f1_per_class"][c]
                for c in C.CLASS_NAMES] for s in series}
    _bars(ax, C.CLASS_NAMES, series, vals, colors, {s: s for s in series})
    _finish(ax, "F1 по класах: float32 проти int8", "F1", 1.08)
    ax.legend(ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    sub = (f'macro-F1 {q["float32"]["macro_f1"]:.4f} -> {q["int8"]["macro_f1"]:.4f}  '
           f'(падіння {q["macro_f1_drop_pp"]:.2f} п., критерій <= '
           f'{q["criteria"]["macro_f1_drop_pp_max"]})')
    ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=8.5, color=C.INK_MUTED)
    return _save(fig, "float_vs_int8.png")


# ── 7. Пам'ять відносно ресурсів плати ───────────────────────────────────────
def memory_usage(cmp: dict, q: dict) -> Path:
    m = cmp["models"][C.CHOSEN]
    flash_f32 = m["weights_bytes_f32"] / 1024
    flash_i8 = (q.get("tflite_bytes", 0) / 1024) if q.get("status") == "ok" else None
    ram = m["activation_bytes"]["peak"] / 1024

    panels = [
        ("Flash", C.MCU["flash_kib"],
         [("ваги float32", flash_f32, C.SERIES["104hz"])]
         + ([(".tflite int8", flash_i8, C.SERIES["52hz"])] if flash_i8 else [])),
        ("RAM (активації)", C.MCU["ram_kib"], [("пік", ram, C.SERIES["104hz"])]),
    ]
    rows = max(len(items) for _, _, items in panels)
    fig, axes = plt.subplots(1, 2, figsize=(10, 1.1 + 0.7 * rows))
    for ax, (title, cap, items) in zip(axes, panels):
        ypos = np.arange(len(items))
        ax.barh(ypos, cap, color="#ebeae5", height=0.5, linewidth=0)
        for i, (_, v, col) in enumerate(items):
            ax.barh(i, v, color=col, height=0.5, linewidth=0, zorder=2)
            ax.text(v + cap * 0.02, i, f"{v:.0f} КіБ · {v / cap * 100:.1f} %",
                    va="center", fontsize=9, color=C.INK, zorder=3)
        limit = cap * (1 - C.CRITERIA["memory_headroom_frac"])
        ax.axvline(limit, color=C.STATUS["SKIP"], lw=1.4, ls="--", zorder=4)
        ax.annotate(f'межа запасу {int(C.CRITERIA["memory_headroom_frac"] * 100)} %',
                    xy=(limit, 1.0), xycoords=("data", "axes fraction"),
                    xytext=(0, 5), textcoords="offset points",
                    fontsize=8, color=C.INK_MUTED, ha="center")
        ax.set_yticks(ypos, [n for n, _, _ in items])
        ax.set_xlim(0, cap * 1.32)
        ax.set_ylim(-0.75, rows - 0.25)
        ax.set_xlabel(f"КіБ з {cap} доступних")
        ax.set_title(title, color=C.INK, loc="left", pad=16)
        ax.set_axisbelow(True)
        ax.xaxis.grid(True)
        ax.yaxis.grid(False)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
    title = ("Пам" + chr(39) + "ять моделі " + m["label"]
             + " на " + C.MCU["name"])
    fig.suptitle(title, color=C.INK, x=0.008, ha="left",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    return _save(fig, "memory_usage.png")


# ── 8. Паритет препроцесингу ─────────────────────────────────────────────────
def preprocessing_parity(p: dict) -> Path:
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    if p.get("status") != "ok":
        ax.axis("off")
        ax.text(0.5, 0.5, "Тест паритету не виконувався\n\n" + p.get("reason", ""),
                ha="center", va="center", fontsize=11, color=C.INK_MUTED)
        return _save(fig, "preprocessing_parity.png")
    names = ["без фільтра\n(як при навчанні)", "з ФНФ плати 25 Гц\n(причинний)"]
    vals = [p["without_filter"]["macro_f1"], p["with_board_filter"]["macro_f1"]]
    cols = [C.SERIES["104hz"], C.SERIES["27hz"]]
    b = ax.bar(names, vals, width=0.5, color=cols, linewidth=0)
    ax.bar_label(b, fmt="{:.4f}", padding=3, fontsize=9.5, color=C.INK)
    _finish(ax, "Паритет препроцесингу ПК і плати", "macro-F1 на test", max(vals) * 1.18)
    ax.text(0, 1.03, f'падіння {p["macro_f1_drop_pp"]:.2f} п., критерій <= '
                     f'{p["criteria"]["macro_f1_drop_pp_max"]} п.',
            transform=ax.transAxes, fontsize=9, color=C.INK_MUTED)
    return _save(fig, "preprocessing_parity.png")


# ── 9. Підсумкова таблиця ────────────────────────────────────────────────────
def validation_summary(rows: list[dict]) -> Path:
    import textwrap

    wrapped = [textwrap.wrap(r["detail"], 46) or [""] for r in rows]
    heights = [max(1, len(w)) for w in wrapped]
    body = sum(heights)
    header = 2.0
    unit_in = 0.30
    fig, ax = plt.subplots(figsize=(11.2, (body + header) * unit_in + 0.25))
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, body + header)
    top = body + header

    ax.text(0.0, top - 0.6, "Тести підтвердження вибору моделі",
            fontsize=13, fontweight="bold", color=C.INK, va="center")
    for x, t, ha in ((0.0, "тест", "left"), (0.42, "результат", "left"),
                     (0.9325, "статус", "center")):
        ax.text(x, top - 1.55, t, fontsize=9.5, color=C.INK_MUTED,
                fontweight="bold", ha=ha, va="center")
    ax.plot([0, 1], [top - header, top - header], color=C.GRID, lw=1.1)

    y = top - header
    for r, lines, h in zip(rows, wrapped, heights):
        mid = y - h / 2
        ax.text(0.0, mid, r["name"], fontsize=9.5, color=C.INK, va="center")
        ax.text(0.42, mid, chr(10).join(lines), fontsize=8.8, color=C.INK_MUTED,
                va="center", linespacing=1.6)
        st = r["status"]
        mark = {"PASS": "+", "FAIL": "x", "SKIP": "~"}[st]
        ax.add_patch(plt.Rectangle((0.875, mid - 0.32), 0.115, 0.64,
                                   facecolor=C.STATUS[st], edgecolor="none",
                                   alpha=0.16, zorder=1))
        ax.text(0.9325, mid, f"{mark} {st}", fontsize=9.5, color=C.STATUS[st],
                va="center", ha="center", fontweight="bold")
        y -= h
        ax.plot([0, 1], [y, y], color=C.GRID, lw=0.6)
    return _save(fig, "validation_summary.png")


# ── 10. Фактичний ODR на платі ───────────────────────────────────────────────
def board_odr(o: dict) -> Path:
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    nominal = o["nominal_hz"]
    tol = 2.0
    lo, hi = nominal * (1 - tol / 100), nominal * (1 + tol / 100)
    ax.axhspan(lo, hi, color=C.STATUS["PASS"], alpha=0.12, zorder=0)
    ax.axhline(nominal, color=C.INK_MUTED, lw=1.1, ls="--", zorder=1)

    names = ["оброблено\nпрошивкою", "втрачено\nпід час інференсу", "фактичний ODR\nдатчика"]
    vals = [o["processed_hz"], o["dropped_per_s"], o["actual_hz"]]
    cols = [C.SERIES["27hz"], C.SERIES["52hz"], C.SERIES["104hz"]]
    b = ax.bar(names, vals, width=0.52, color=cols, linewidth=0, zorder=3)
    ax.bar_label(b, fmt="{:.1f} Гц", padding=3, fontsize=9.5, color=C.INK)
    ax.annotate(f"номінал {nominal:g} Гц, допуск ±{tol:g} %",
                xy=(2.45, nominal), xytext=(0, 6), textcoords="offset points",
                fontsize=8.5, color=C.INK_MUTED, ha="right")
    _finish(ax, "Фактична частота дискретизації на платі", "Гц", max(vals) * 1.25)
    ax.title.set_position((0.0, 1.0))
    ax.set_title("Фактична частота дискретизації на платі", color=C.INK,
                 loc="left", pad=26)
    ax.text(0, 1.02, f'відхилення {o["deviation_pct"]:+.1f} % — вікно 208 відліків '
                     f'триває {o["window_seconds"]:.2f} с замість 2.00 с',
            transform=ax.transAxes, fontsize=9, color=C.STATUS["FAIL"])
    return _save(fig, "board_odr.png")


# ── 11. Час інференсу на платі ───────────────────────────────────────────────
def board_inference(i: dict, debug_ms: float | None = None) -> Path:
    fig, ax = plt.subplots(figsize=(7.6, 3.2))
    budget = i["hop_budget_ms"]
    items = [("крок вікна (бюджет)", budget, "#ebeae5")]
    if debug_ms:
        items.append(("Debug, -O0", debug_ms, C.SERIES["52hz"]))
    items.append((f'{i.get("build", "Release")}', i["ms_avg"], C.SERIES["104hz"]))
    y = np.arange(len(items))
    for k, (name, v, col) in enumerate(items):
        ax.barh(k, v, color=col, height=0.5, linewidth=0, zorder=2)
        ax.text(v + budget * 0.015, k, f"{v:.1f} мс", va="center", fontsize=9.5, color=C.INK)
    ax.set_yticks(y, [n for n, _, _ in items])
    ax.set_xlim(0, budget * 1.22)
    ax.set_xlabel("мс на одне вікно")
    ax.set_title("Час інференсу на платі проти бюджету", color=C.INK, loc="left", pad=26)
    ax.set_axisbelow(True)
    ax.xaxis.grid(True)
    ax.yaxis.grid(False)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.text(0, 1.02, f'{i["ms_avg"]:.1f} мс = {i["budget_used_frac"]*100:.1f} % бюджету',
            transform=ax.transAxes, fontsize=9, color=C.INK_MUTED)
    return _save(fig, "board_inference_time.png")
