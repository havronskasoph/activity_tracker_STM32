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
| Режим | ODR 26 Гц (measured: 27.45 Hz), ±4 g, ±2000 dps, читання за сигналом data-ready |
| Формат виводу | `timestamp_ms,ax,ay,az,gx,gy,gz` |
| Одиниці | accel in m/s² (gravity included), gyro in °/s |
| Канал | USART1, 115200 8N1, `printf` перенаправлено на UART |

Запис потоку в CSV: `python tools/log.py COM3 <клас> <людина>` (потрібен `pip install pyserial`, зупинка Ctrl+C). Файли потрапляють у `data/`.

| Документ | Про що |
|---|---|
| `firmware/activity_tracker_fw/` | Проєкт STM32CubeMX/CubeIDE (код датчика в `Core/Src/main.c`, драйвер `ism330dhcx_reg.*`) |
| `tools/log.py` | Запис потоку з COM-порту в CSV |
| `data/` | Records from the sensor. `sitting_*`: mg/mdps, 7 columns. `drdytest_*`: m/s², accel only, 4 columns. New recordings: m/s² + °/s, 7 columns |

**Збірка:** STM32CubeIDE → Import → Existing Projects into Workspace → `firmware/activity_tracker_fw` (без Copy), Build, Run. Версія пакета STM32Cube_FW_U5_V1.9.0.

**Правила роботи з `.ioc`:** редагує один учасник за раз, свій код пишемо лише між `USER CODE BEGIN/END`, перед регенерацією робимо коміт.

**Status:** accelerometer, UART and logging work on the board. Gyroscope output is added in
firmware but not yet tested on the board. Next: verify the gyro, re-measure the sample rate,
buffer 55-sample windows and integrate the model.

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
