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
The model for the current firmware runs at 27.45 Hz on 2 s windows (55 × 6) and scores
**83.8 %** accuracy / **0.817** macro-F1 on held-out people.

| | |
|---|---|
| [ml/README.md](ml/README.md) | Setup, training, results, inference API for teammates, firmware requirements |
| `ml/har/` | Training, evaluation and inference code |
| `ml/models/` | Trained models with metrics and plots |

The dataset is not stored in git; `python -m har.train --download` fetches it.
