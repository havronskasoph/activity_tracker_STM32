# activity_tracker_STM32

Трекер фізичної активності на STM32: плата читає акселерометр і гіроскоп (6 осей) і класифікує
активність нейромережею безпосередньо на мікроконтролері.

Розпізнавані класи: `Lying`, `Stationary`, `Walking`, `Running`, `Stairs`.

Платформа — B-U585I-IOT02A (STM32U585AIIxQ).

## Прошивка і дані з датчика

Плата читає акселерометр і гіроскоп ISM330DHCX по I2C і виводить потік через UART (ST-LINK Virtual COM Port).

| Параметр | Значення |
|---|---|
| Датчик | ISM330DHCX, I2C2, адреса 0x6B (перевірка через WHO_AM_I) |
| Режим | ODR 104 Гц (виміряно: 109.8 Гц), ±4 g, ±2000 dps, читання за сигналом data-ready |
| Формат виводу | `# pred t=<мс> class=<клас> p=<імовірність>` раз на вікно; CSV `timestamp_ms,ax,ay,az,gx,gy,gz` вмикається `HAR_STREAM_CSV 1` |
| Одиниці | акселерометр у g (гравітація не віднімається), гіроскоп у °/с |
| Канал | USART1, 115200 8N1, `printf` перенаправлено на UART |

Запис потоку в CSV: `python tools/log.py COM3 <клас> <людина>` (потрібен `pip install pyserial`, зупинка Ctrl+C). Файли потрапляють у `data/`.

| Документ | Про що |
|---|---|
| `firmware/activity_tracker_fw/` | Проєкт STM32CubeMX/CubeIDE: збір із датчика, препроцесинг і інференс на платі |
| `Core/Src/har_preproc.c` | ФНЧ 25 Гц, накопичення вікна 208 × 6, нормалізація |
| `Core/Src/har_model.c` | Інференс ST-IGN: власна C-реалізація, без зовнішнього рантайму |
| `Core/Inc/har_model_weights.h` | Ваги моделі, 111 077 чисел float32; генерується `validation/scripts/export_weights.py` |
| `Core/Inc/har_model_config.h` | **Згенерований** із датасету: частота, вікно, класи, mean/std, коефіцієнти ФНЧ |
| `Core/Inc/har_test_vectors.h` | 50 векторів для самоперевірки на платі (`HAR_SELFTEST 1`) |
| `tools/log.py` | Запис потоку з COM-порту в CSV |
| `data/` | Records from the sensor. `sitting_*`: mg/mdps, 7 columns. `drdytest_*`: m/s², accel only, 4 columns. New recordings: m/s² + °/s, 7 columns |

**Збірка:** STM32CubeIDE → Import → Existing Projects into Workspace → `firmware/activity_tracker_fw` (без Copy), Build, Run. Версія пакета STM32Cube_FW_U5_V1.9.0.

**Правила роботи з `.ioc`:** редагує один учасник за раз, свій код пишемо лише між `USER CODE BEGIN/END`, перед регенерацією робимо коміт.

**Статус:** модель розгорнута й працює на платі. Повний цикл виконується автономно:
плата читає 6 осей на 104 Гц, фільтрує ФНЧ 25 Гц, набирає вікно 208 × 6, нормалізує
і класифікує — результат іде в UART рядком `# pred`.

На платі `st_ign_var2_104hz` у float32. ST Edge AI Core не спрацював ні локально, ні через
хмару, тому інференс написаний власним C-кодом і звірений із Python на всьому тестовому
наборі: 11 841 з 11 841 вікон дають той самий клас. На самій платі 50 з 50 тестових
векторів збігаються з ПК.

Release (`-Os`): Flash 468 КіБ із 2048, RAM 50 КіБ із 768, інференс 34.7 мс на вікно при
кроці в 1 секунду.

**Конфігурація за замовчуванням:** `HAR_SELFTEST 0`, `HAR_STREAM_CSV 0` — робочий режим
інференсу без потоку CSV. Для збору даних увімкни `HAR_STREAM_CSV 1`; після будь-якої
зміни моделі — `HAR_SELFTEST 1`, очікуваний результат `# selftest match=50/50`.

**Відоме обмеження:** датчик іде на 5.6 % швидше за номінал — замовлені 104 Гц дають 109.8.
Вікно з 208 відліків триває 1.89 с замість 2.00 с, на яких навчена модель. Вимірювання
й деталі — у [validation/VALIDATION.md](validation/VALIDATION.md).

Перевірки, метрики, графіки й логи з плати — у теці [validation/](validation/);
обґрунтування вибору моделі — [validation/model_selection_report.pdf](validation/model_selection_report.pdf).

## ML part

Our own 6-axis model (accelerometer + gyroscope), ST-IGN architecture from the
[STM32 AI Model Zoo](https://github.com/STMicroelectronics/stm32ai-modelzoo-services), trained on the
[RealWorld HAR](https://github.com/alinaytsk/har-realworld-dataset) upper-arm dataset.
Three trained variants are available. The **27.45 Hz** model matches the current board sampling rate
and scores **83.8 %** test accuracy / **0.817** macro-F1. The new **104 Hz** model uses 2 s windows
(208 × 6) and scores **82.0 %** / **0.803** on the held-out test subjects. It is not a drop-in model
for the current 27.45 Hz firmware; use it when the board input is sampled at 104 Hz and prefiltered
to 25 Hz. Its training data was resampled from RealWorld's approximately 50 Hz recordings, so 104 Hz
aligns the model input format with the sensor but does not add signal detail above the source's 25 Hz
Nyquist limit.

Prepared 104 Hz data is stored locally in `ml/data/har_var2/` and excluded from git. Model metrics,
training commands, and inference requirements are documented in [ml/README.md](ml/README.md).

| | |
|---|---|
| [ml/README.md](ml/README.md) | Setup, training, results, inference API for teammates, firmware requirements |
| `ml/har/` | Training, evaluation and inference code |
| `ml/models/` | Trained models with metrics and plots, including `st_ign_var2_104hz/` |

The original 52 Hz training dataset can be fetched with `python -m har.train --download`. The prepared
104 Hz dataset is local-only; its source pipeline checkout is in `ml/data/har_var2_source/` and is
also excluded from git.
