# validation — тести підтвердження вибору моделі

Відтворюваний набір тестів, який обґрунтовує вибір **`st_ign_realworld_imu_27hz`** для
деплою на STM32U585. Результати й графіки — у [VALIDATION.md](VALIDATION.md).

## Запуск однією командою

```bash
python validation/run_all.py
```

Скрипт рахує всі тести, кладе метрики в `results/*.json`, малює `figures/*.png`,
генерує тестові вектори у `test_vectors/` і наприкінці запускає `pytest`.
Запускати з кореня репозиторію. Прогін займає близько 5 хвилин.

Окремо лише перевірки, без перерахунку (якщо `results/` уже заповнений):

```bash
pytest validation/tests -v -p no:cacheprovider
```

`-p no:cacheprovider` потрібен, щоб pytest не створював `.pytest_cache/` у корені
репозиторію — `validation/.gitignore` до нього не дотягується. `run_all.py`
додає цей прапорець сам. Як альтернатива — допиши `.pytest_cache/` у `.gitignore`
репозиторію.

## Що треба встановити

Середовище створюється **поза репозиторієм**, щоб не потрапити в git:

```bash
python -m venv ../.venv-validation
../.venv-validation/Scripts/python -m pip install -r ml/requirements-har.txt pytest
```

На Linux і macOS шлях до інтерпретатора — `../.venv-validation/bin/python`.

| Потрібне | Для чого | Якщо немає |
|---|---|---|
| numpy, scipy, scikit-learn, matplotlib, h5py | тести 1, 5, 6 | тести не запустяться |
| TensorFlow 2.21 + Keras 3.15 | тест 2 (квантування int8) | тест 2 → SKIP |
| ST Edge AI Core | тести 3 і 4 | тести 3 і 4 → SKIP |

Інференс у тестах 1, 5 і 6 рахується на чистому NumPy
(`scripts/stign_numpy.py`), тому TensorFlow для них не потрібен. Відповідність
цієї реалізації перевіряє сам тест 1: він звіряє обчислені метрики з тими, що
записані в `model_meta.json` кожної моделі, і вимагає збігу до 1e-9.

### ST Edge AI Core

Завантажується з сайту ST (потрібен акаунт): **ST Edge AI Core** або
X-CUBE-AI у складі STM32CubeMX. Після встановлення або додай `stedgeai` у `PATH`,
або вкажи шлях явно:

```bash
export STEDGEAI_PATH="C:/ST/STEdgeAI/2.2/Utilities/windows/stedgeai.exe"
```

Після цього `python validation/run_all.py` зробить тести 3 і 4 без жодних правок коду.

## Де лежать датасети

Датасети в цьому репозиторії не зберігаються — вони в окремих репозиторіях.
Шляхи за замовчуванням розраховані на розкладку, де всі репо лежать поруч:

```
project/
  activity_tracker_STM32/          <- цей репозиторій
  har-dataset/                     <- 52 Гц
  variant_104hz/
    har-dataset_var2/              <- 104 Гц, для порівняння варіантів
    activity_tracker_STM32_var2/   <- архів варіанта 104 Гц
```

Якщо розкладка інша, задай змінні оточення:

| Змінна | Що це | Типово |
|---|---|---|
| `HAR_DATASET_52HZ` | `data/processed` датасету 52 Гц | `../har-dataset/data/processed` |
| `HAR_DATASET_104HZ` | `data/processed` датасету 104 Гц | `../variant_104hz/har-dataset_var2/data/processed` |
| `HAR_FIRMWARE_HEADER` | `har_model_config.h` прошивки | `firmware/activity_tracker_fw/Core/Inc/` цього репо |
| `STEDGEAI_PATH` | виконуваний файл ST Edge AI Core | `stedgeai` з `PATH` |

Якщо датасет не знайдено, скрипт падає з повідомленням, яку саме змінну задати.

## Структура

| Шлях | Що всередині |
|---|---|
| `run_all.py` | запускає всі тести, зберігає метрики й графіки |
| `scripts/config.py` | шляхи, реєстр моделей, константи плати, критерії, палітра |
| `scripts/stign_numpy.py` | прямий прохід ST-IGN на NumPy, без TensorFlow |
| `scripts/datasets.py` | завантаження даних так само, як це робив `train.py` |
| `scripts/steps.py` | обчислення тестів 1, 5, 6 і виправлені метадані |
| `scripts/quantize.py` | тест 2: PTQ в int8 через TFLite |
| `scripts/stedgeai.py` | тести 3 і 4: обгортка ST Edge AI Core |
| `scripts/export_weights.py` | експорт ваг моделі у C-заголовок для прошивки |
| `scripts/board.py` | зчитування й розбір показників із плати |
| `scripts/report_pdf.py`, `scripts/defense_pdf.py` | генератори двох PDF-звітів |
| `scripts/plotting.py` | усі графіки, єдиний стиль |
| `board_logs/` | сирі логи з плати — щоб перерахувати результати без неї |
| `tests/` | pytest-тести з критеріями |
| `results/` | `*.json` з метриками кожного тесту |
| `figures/` | `*.png`, dpi 150 |
| `test_vectors/` | 50 вікон для плати + очікувані виходи, див. README поруч |

## Критерії тестів

| # | Тест | Критерій |
|---|---|---|
| 1 | Порівняння трьох моделей | метрики відтворюються до 1e-9; обрана модель сумісна з платою |
| 2 | Квантування int8 | падіння macro-F1 ≤ 1.5 п., F1 Walking ≤ 3 п. |
| 3 | ST Edge AI analyze | запас ≥ 50 % від 2048 КіБ Flash і 768 КіБ RAM |
| 4 | ST Edge AI validate | збіг argmax 100 % |
| 5 | Паритет препроцесингу | падіння macro-F1 від ФНЧ плати ≤ 1 п. |
| 6 | Тестові вектори | 50 вікон згенеровано і самоузгоджені; на платі ≥ 98 % збігу |

Недоступний інструмент дає **SKIP із причиною**, а не FAIL.
