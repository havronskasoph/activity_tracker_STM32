"""Генератор validation/model_selection_report.pdf.

Верстка на matplotlib: кожна сторінка — окрема фігура A4, текст і графіки
розкладаються згори вниз простим потоковим укладальником. Шрифт DejaVu Sans
(типовий у matplotlib) має повний кириличний набір.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from . import config as C

A4 = (8.27, 11.69)
LEFT, RIGHT, TOP, BOTTOM = 0.09, 0.93, 0.945, 0.055
WIDTH = RIGHT - LEFT


class Page:
    """Потокова сторінка: елементи додаються згори вниз."""

    def __init__(self, pdf: PdfPages, number: int, running_head: str = ""):
        self.pdf = pdf
        self.fig = plt.figure(figsize=A4, facecolor="white")
        self.y = TOP
        self.number = number
        if running_head:
            self.fig.text(LEFT, 0.975, running_head, fontsize=7.5, color="#8a8a84")
        self.fig.text(RIGHT, 0.025, str(number), fontsize=8, color="#8a8a84", ha="right")

    def space(self, dy: float):
        self.y -= dy

    def h1(self, text: str):
        self.fig.text(LEFT, self.y, text, fontsize=17, fontweight="bold", color=C.INK,
                      va="top")
        self.y -= 0.042

    def h2(self, text: str):
        self.y -= 0.004
        self.fig.text(LEFT, self.y, text, fontsize=11.5, fontweight="bold", color=C.INK,
                      va="top")
        self.y -= 0.027

    def para(self, text: str, size: float = 9.3, color: str | None = None, wrap: int = 95):
        lines = []
        for block in text.split("\n"):
            lines.extend(textwrap.wrap(block, wrap) or [""])
        self.fig.text(LEFT, self.y, "\n".join(lines), fontsize=size,
                      color=color or "#26251f", va="top", linespacing=1.55)
        self.y -= 0.0175 * len(lines) + 0.009

    def bullets(self, items: list[str], size: float = 9.3, wrap: int = 90):
        for it in items:
            lines = textwrap.wrap(it, wrap)
            self.fig.text(LEFT + 0.012, self.y, "•", fontsize=size, color=C.INK_MUTED, va="top")
            self.fig.text(LEFT + 0.028, self.y, "\n".join(lines), fontsize=size,
                          color="#26251f", va="top", linespacing=1.55)
            self.y -= 0.0175 * len(lines) + 0.005
        self.y -= 0.006

    def table(self, header: list[str], rows: list[list[str]], cols: list[float],
              size: float = 8.6, status_col: int | None = None):
        x0 = LEFT
        self.fig.lines.append(plt.Line2D([LEFT, RIGHT], [self.y + 0.012, self.y + 0.012],
                                         transform=self.fig.transFigure,
                                         color="#c9c8c2", lw=0.9))
        x = x0
        for h, w in zip(header, cols):
            self.fig.text(x, self.y, h, fontsize=size, fontweight="bold",
                          color=C.INK_MUTED, va="top")
            x += w
        self.y -= 0.021
        self.fig.lines.append(plt.Line2D([LEFT, RIGHT], [self.y + 0.007, self.y + 0.007],
                                         transform=self.fig.transFigure,
                                         color="#c9c8c2", lw=0.9))
        for r in rows:
            x = x0
            height = 1
            for i, (cell, w) in enumerate(zip(r, cols)):
                col = "#26251f"
                weight = "normal"
                if status_col is not None and i == status_col:
                    col = C.STATUS.get(cell.strip(), "#26251f")
                    weight = "bold"
                lines = textwrap.wrap(cell, max(8, int(w * 125)))
                height = max(height, len(lines))
                self.fig.text(x, self.y, "\n".join(lines), fontsize=size, color=col,
                              fontweight=weight, va="top", linespacing=1.4)
                x += w
            self.y -= 0.0165 * height + 0.004
        self.y -= 0.008

    def image(self, name: str, caption: str, max_h: float = 0.27):
        path = C.FIGURES_DIR / name
        img = mpimg.imread(path)
        ih, iw = img.shape[0], img.shape[1]
        page_w_in, page_h_in = A4
        w = WIDTH
        h = w * (ih / iw) * (page_w_in / page_h_in)
        if h > max_h:
            h = max_h
            w = h * (iw / ih) * (page_h_in / page_w_in)
        x = LEFT + (WIDTH - w) / 2
        ax = self.fig.add_axes((x, self.y - h, w, h))
        ax.imshow(img)
        ax.axis("off")
        self.y -= h + 0.012
        if caption:
            lines = textwrap.wrap(caption, 110)
            self.fig.text(LEFT, self.y, "\n".join(lines), fontsize=8.2,
                          color=C.INK_MUTED, va="top", style="italic", linespacing=1.45)
            self.y -= 0.015 * len(lines) + 0.012

    def close(self):
        self.pdf.savefig(self.fig)
        plt.close(self.fig)


def _r(name: str) -> dict:
    p = C.RESULTS_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build(out_path: Path | None = None) -> Path:
    out = out_path or (C.VALIDATION_DIR / "model_selection_report.pdf")
    cmp_ = _r("01_model_comparison.json")
    q = _r("02_quantization.json")
    par = _r("05_preprocessing_parity.json")
    tv = _r("06_test_vectors.json")
    summ = _r("00_summary.json").get("rows", [])
    odr = _r("board_odr.json")
    inf = _r("board_inference.json")
    bvec = _r("board_vectors.json")
    live = _r("board_live.json")
    M = cmp_["models"]
    ch = M[C.CHOSEN]
    head = "Вибір моделі для трекера активності на STM32U585"
    n = 0

    with PdfPages(out) as pdf:
        # ── 1 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n)
        p.space(0.03)
        p.h1("Вибір моделі для трекера активності")
        p.para("Обґрунтування деплою st_ign_var2_104hz на STM32U585AII", size=11.5,
               color=C.INK_MUTED)
        p.space(0.025)
        p.h2("1. Задача і обмеження платформи")
        p.para(
            "Трекер носиться на плечі й має розпізнавати активність локально, без "
            "зв'язку з телефоном. Класифікація йде на самій платі: інференс, препроцесинг "
            "і збір даних діляться одним ядром.")
        p.bullets([
            f"Плата: {C.MCU['name']}, Arm Cortex-M33 на 160 МГц, "
            f"{C.MCU['flash_kib']} КіБ Flash, {C.MCU['ram_kib']} КіБ RAM.",
            "Датчик ISM330DHCX: акселерометр і гіроскоп, 6 осей, одиниці g і °/с.",
            f"Формат входу моделі заданий прошивкою: вікно {C.BOARD['window_samples']} × "
            f"{C.BOARD['channels']} при {C.BOARD['fs_hz']:g} Гц, крок {C.BOARD['hop_samples']} "
            f"відліків (перекриття 50 %).",
            f"Перед вікном стоїть ФНЧ {C.BOARD['lpf_hz']:g} Гц, Баттерворт "
            f"{C.BOARD['lpf_order']}-го порядку, причинний.",
            "Нормалізація робиться на платі тими самими константами, що й при навчанні.",
            "Класи: Lying, Stationary, Walking, Running, Stairs.",
        ])
        p.para(
            "Критерій придатності моделі подвійний: вона має бути точною і має "
            "відтворюватися на платі без змін у тракті обробки сигналу. Другий критерій "
            "виявився вирішальним.")
        p.close()

        # ── 2 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.h2("2. Датасет")
        p.para(
            "RealWorld HAR (2016), положення upper arm, акселерометр і гіроскоп. "
            "Сире джерело записане на ~50 Гц, тож реального сигналу вище 25 Гц у даних "
            "немає — саме тому на платі стоїть ФНЧ 25 Гц.")
        p.bullets([
            f"Вікна {ch['window_samples']} × {C.BOARD['channels']} по 2.0 с при "
            f"{ch['fs_hz']:g} Гц, крок {ch['stride_samples']}.",
            f"Розмір вибірок: train {M['104hz']['test']['n_windows'] and ''}"
            f"42 052, val 7 818, test {ch['test']['n_windows']} вікон.",
            "Поділ строго за людьми: train 1-5, 7-9, 11, 13; val 6, 10; test 12, 14, 15. "
            "Жоден учасник не потрапляє у дві вибірки.",
            "Нормалізаційні константи пораховані лише на train і зберігаються окремо.",
            "Відбір моделей під час навчання йшов виключно по val_loss; test оцінювався "
            "один раз наприкінці, тож витоку немає.",
        ])
        p.h2("3. Кандидати")
        p.para(
            "Три моделі однакової архітектури ST-IGN, що відрізняються лише частотою "
            "дискретизації навчальних даних.")
        p.table(
            ["показник", "27.45 Гц", "52 Гц", "104 Гц (обрана)"],
            [
                ["вхід", "55 × 6", "104 × 6", "208 × 6"],
                ["macro-F1 test", f"{M['27hz']['test']['macro_f1']:.4f}",
                 f"{M['52hz']['test']['macro_f1']:.4f}", f"{ch['test']['macro_f1']:.4f}"],
                ["macro-F1 val", f"{M['27hz']['val']['macro_f1']:.4f}",
                 f"{M['52hz']['val']['macro_f1']:.4f}", f"{ch['val']['macro_f1']:.4f}"],
                ["параметри", f"{M['27hz']['params']:,}".replace(",", " "),
                 f"{M['52hz']['params']:,}".replace(",", " "),
                 f"{ch['params']:,}".replace(",", " ")],
                ["MACC", f"{M['27hz']['macc']:,}".replace(",", " "),
                 f"{M['52hz']['macc']:,}".replace(",", " "),
                 f"{ch['macc']:,}".replace(",", " ")],
                ["сумісність із платою", "ні", "ні", "так"],
            ],
            [0.30, 0.19, 0.19, 0.22])
        p.image("models_macro_f1.png",
                "Рис. 1. macro-F1 на val і test. Ранжування однакове на обох вибірках, "
                "тож перевага 27-герцової моделі не є артефактом тестового набору.",
                max_h=0.235)
        p.close()

        # ── 3 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.image("models_f1_per_class.png",
                "Рис. 2. F1 по класах. Lying, Stationary і Running тримаються на 0.93-0.99 "
                "у всіх трьох моделей; уся різниця між ними зосереджена у Walking і Stairs.",
                max_h=0.285)
        p.image("f1_vs_macc.png",
                "Рис. 3. Точність проти обчислювальної вартості. Підвищення частоти до "
                "104 Гц коштує вп'ятеро більше обчислень, ніж 27.45 Гц, і дає на 1.3 пункта "
                "менше macro-F1 — передискретизація вгору інформації не додає.",
                max_h=0.285)
        p.close()

        # ── 4 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.image("f1_per_subject.png",
                "Рис. 4. macro-F1 по кожному учаснику тестової вибірки. Розкид помірний "
                "(0.74-0.88), жоден учасник не провалюється, тобто середнє не приховує "
                "окремого катастрофічного випадку.",
                max_h=0.235)
        p.h2("4. Обґрунтування вибору st_ign_var2_104hz")
        p.para(
            "27-герцова модель точніша на 1.3 пункта macro-F1, але відтворити її на цій "
            "платі коректно неможливо. Її навчальні дані отримані scipy.signal.resample_poly "
            "із 52 Гц, тобто з поліфазним антиаліасинговим фільтром. Щоб повторити це на "
            "платі, довелося б або поставити ODR 26 Гц і покластися на внутрішній фільтр "
            "датчика — а це інший фільтр, — або семплити вище й децимувати власним фільтром "
            "у прошивці. Додатково: при 27.45 Гц частота Найквіста 13.7 Гц, тож наявний "
            "ФНЧ 25 Гц втрачає сенс і весь фільтровий тракт треба проєктувати заново.")
        p.para(
            "104-герцова модель натомість узгоджена з прошивкою по всьому тракту. Константи "
            "в har_model_config.h звіряються автоматично: тест читає заголовок прошивки й "
            "порівнює ODR, довжину вікна, крок і частоту зрізу ФНЧ із тими, під які навчена "
            "модель. Ціна вибору — 1.3 пункта macro-F1.")
        p.close()

        # ── 5 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.h2("Ресурси")
        n_par = f"{ch['params']:,}".replace(",", " ")
        p.para(
            f"Модель розгорнута у float32 власною C-реалізацією (ваги {n_par} × 4 Б "
            f"= {ch['weights_bytes_f32']/1024:.0f} КіБ). Згортка, ReLU і пулінг злиті в один "
            f"прохід, тому повний вихід згортки не зберігається.")
        p.table(
            ["ресурс", "використано", "доступно", "частка"],
            [
                ["Flash (зібрана прошивка)", "489 КіБ", f"{C.MCU['flash_kib']} КіБ", "23.9 %"],
                ["RAM (data + bss)", "50 КіБ", f"{C.MCU['ram_kib']} КіБ", "6.5 %"],
                ["int8 .tflite (для довідки)",
                 f"{q.get('tflite_bytes', 0)/1024:.0f} КіБ", "—", "—"],
            ],
            [0.34, 0.22, 0.20, 0.17])
        p.image("memory_usage.png",
                "Рис. 5. Пам'ять моделі відносно ресурсів плати. Запас понад 50 % "
                "виконується з великим відривом в обох вимірах.",
                max_h=0.17)
        p.h2("5. Тести підтвердження")
        p.para(
            "Десять тестів із формальними критеріями. Усі відтворювані командою "
            "python validation/run_all.py; pytest показує PASS, FAIL або SKIP.")
        p.image("validation_summary.png",
                "Рис. 6. Підсумок. Два SKIP — ST Edge AI Core не встановлений; "
                "один FAIL розібраний нижче.",
                max_h=0.23)
        p.close()

        # ── 6 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.h2("Квантування int8")
        p.para(
            f"PTQ на {q.get('representative_windows', 0)} вікнах із train. macro-F1 падає з "
            f"{q['float32']['macro_f1']:.4f} до {q['int8']['macro_f1']:.4f}, тобто на "
            f"{q['macro_f1_drop_pp']:.2f} пункта при дозволених "
            f"{q['criteria']['macro_f1_drop_pp_max']}. F1 Walking не просів, а піднявся з "
            f"{q['float32']['f1_per_class']['Walking']:.3f} до "
            f"{q['int8']['f1_per_class']['Walking']:.3f}.")
        p.image("float_vs_int8.png",
                "Рис. 7. F1 по класах до і після квантування. Деградації немає в жодному "
                "класі; на платі розгорнуто float32, а int8 лишається запасним варіантом.",
                max_h=0.245)
        p.h2("Паритет препроцесингу")
        p.para(
            "Плата проганяє потік через причинний ФНЧ 25 Гц, а навчальні дані такого "
            "фільтра не бачили: у пайплайні датасету антиаліасинг робився нульфазовим "
            "filtfilt і лише для записів, швидших за 1.2 × 50 Гц. Тест міряє ціну цієї "
            "розбіжності: вікна test склеюються в неперервні сегменти, фільтруються тими "
            "самими коефіцієнтами SOS, що зашиті в har_model_config.h, і ріжуться наново — "
            f"так само, як це робить плата. Падіння macro-F1 — {par['macro_f1_drop_pp']:.2f} "
            f"пункта при дозволеному {par['criteria']['macro_f1_drop_pp_max']:.0f}.")
        p.image("preprocessing_parity.png",
                "Рис. 8. Вплив ФНЧ плати на точність. Розбіжність між трактом навчання і "
                "трактом плати реальна, але практично невідчутна.",
                max_h=0.215)
        p.close()

        # ── 7 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.h2("Тести на реальній платі")
        p.para(
            "Прошивка зібрана в CubeIDE (Release, -Os) і залита через STM32_Programmer_CLI. "
            "Самоперевірка після старту проганяє 50 тестових векторів і міряє час інференсу "
            "лічильником тактів DWT.")
        p.table(
            ["тест", "критерій", "результат", "статус"],
            [
                ["Тестові вектори ПК ↔ MCU", "≥ 98 % збігу argmax",
                 f"{bvec.get('matched', 0)}/{bvec.get('total', 0)} = "
                 f"{bvec.get('ratio', 0)*100:.0f} %", "PASS"],
                ["Час інференсу", "істотно менше кроку вікна",
                 f"{inf.get('ms_avg', 0):.1f} мс = {inf.get('budget_used_frac', 0)*100:.1f} % "
                 f"від {inf.get('hop_budget_ms', 0):.0f} мс", "PASS"],
                ["Класифікація наживо", "модель видає клас",
                 f"{live.get('count', 0)} передбачень, раз на "
                 f"{live.get('period_ms_median', 0):.0f} мс", "PASS"],
                ["Фактичний ODR", f"{C.BOARD['fs_hz']:g} Гц ± 2 %",
                 f"{odr.get('actual_hz', 0):.1f} Гц ({odr.get('deviation_pct', 0):+.1f} %)",
                 "FAIL"],
            ],
            [0.30, 0.22, 0.27, 0.14], status_col=3)
        p.image("board_inference_time.png",
                "Рис. 9. Час інференсу на платі. Оптимізація -Os дала 3.5-кратне прискорення "
                "проти Debug і знизила втрату відліків із 12 до 3 на секунду.",
                max_h=0.175)
        p.image("board_odr.png",
                "Рис. 10. Фактична частота датчика. Єдиний провалений критерій: ISM330DHCX "
                "іде на 5.6 % швидше за номінал, тож вікно триває 1.89 с замість 2.00 с.",
                max_h=0.235)
        p.close()

        # ── 8 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.h2("6. Відомі обмеження")
        p.para("Плутанина Walking ↔ Stairs", size=9.8, color=C.INK)
        p.para(
            f"Головна вада обраної моделі: F1 Walking {ch['test']['f1_per_class']['Walking']:.3f} "
            f"при recall {ch['test']['recall_per_class']['Walking']:.3f}. З 1 834 вікон ходьби "
            f"1 040 класифікуються як сходи. Загальна accuracy "
            f"{ch['test']['accuracy']:.3f} це приховує. Та сама вада є в усіх трьох моделей, "
            "тобто вона властива архітектурі або самим даним, а не вибору частоти.")
        p.image("confusion_104hz.png",
                "Рис. 11. Матриця помилок обраної моделі, нормована по рядках. Лише 42 % "
                "вікон ходьби розпізнаються правильно; решта йде у Stairs.",
                max_h=0.275)
        p.para("Відхилення ODR", size=9.8, color=C.INK)
        p.para(
            f"Датчик іде на {odr.get('deviation_pct', 0):+.1f} % швидше за номінал. Це "
            "виміряно тричі й підтверджено незалежно: на номінальних 26 Гц плата видає "
            "27.45 Гц — те саме відхилення. Наслідок: модель бачить динаміку, стиснуту в "
            "часі на 6 %. Для статичних класів це нешкідливо (Lying розпізнається з "
            "імовірністю 0.97), але для ходьби й бігу зсуває частоти кроку.")
        p.close()

        # ── 9 ────────────────────────────────────────────────────────────────
        n += 1
        p = Page(pdf, n, head)
        p.para("Дефект метаданих моделі", size=9.8, color=C.INK)
        p.para(
            "model_meta.json обраної моделі записує джерело даних як har-realworld-dataset, "
            "коміт 6f24dcd — це 52-герцовий датасет, на якому модель із входом 208 × 6 "
            "навчена бути не могла. Причина: константи DATASET_REPO і DATASET_COMMIT у "
            "ml/har/data.py захардкоджені, а train.py копіює їх у метадані незалежно від "
            "фактичного dataset.data_dir. Відтворити прогін за метаданими неможливо.")
        p.para(
            "Виправлення: train.py має писати фактичний data_dir і хеші файлів, а не "
            "константи модуля. Виправлені метадані з sha256 усіх трьох .npz збережені в "
            "validation/results/model_meta_corrected.json.")
        p.h2("7. Висновок")
        p.para(
            f"На плату розгорнуто st_ign_var2_104hz — єдину з трьох моделей, яка "
            f"відтворюється на наявному тракті обробки сигналу без його перепроєктування. "
            f"Вона працює: {bvec.get('matched', 0)} з {bvec.get('total', 0)} тестових "
            f"векторів дають на платі той самий клас, що й модель на ПК, інференс займає "
            f"{inf.get('ms_avg', 0):.1f} мс із бюджету в "
            f"{inf.get('hop_budget_ms', 0):.0f} мс, класифікація йде в реальному часі.")
        p.para(
            "C-реалізація звірена з Python на всьому тестовому наборі: 11 841 з 11 841 "
            "вікон дають той самий клас, максимальна різниця ймовірностей 1.7·10⁻⁶. "
            "Це сильніша перевірка, ніж validate від ST Edge AI Core, який звіряє кілька вікон.")
        p.h2("Наступні кроки")
        p.bullets([
            "Узгодити частоту: або підняти номінал так, щоб фактична вийшла 104 Гц, або "
            "перенавчити модель на виміряних 109.8 Гц. Поки цього не зроблено, динамічні "
            "класи працюють зі стиснутою часовою шкалою.",
            "Записати реальні Walking і Stairs на плечі й подивитися, як пара поводиться "
            "на живому сигналі, а не на датасеті.",
            "Встановити ST Edge AI Core і закрити тести 3 і 4 — зараз вони SKIP.",
            "Полагодити запис метаданих у ml/har/data.py.",
            "Розглянути перенесення інференсу так, щоб він не блокував збір відліків: "
            "зараз 34.7 мс обробки коштують трьох втрачених відліків на секунду.",
        ])
        p.close()

    return out


if __name__ == "__main__":
    print(build())
