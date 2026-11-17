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
| Режим | ODR 26 Гц (виміряно: 27.45 Гц — саме на цій частоті навчена модель), ±4 g, ±2000 dps, читання за сигналом data-ready |
| Формат виводу | `# pred t=<мс> class=<клас> p=<імовірність>` раз на вікно; CSV `timestamp_ms,ax,ay,az,gx,gy,gz` вмикається `HAR_STREAM_CSV 1` |
| Одиниці | акселерометр у g (гравітація не віднімається), гіроскоп у °/с |
| Канал | USART1, 115200 8N1, `printf` перенаправлено на UART |

Запис потоку в CSV: `python tools/log.py COM3 <клас> <людина>` (потрібен `pip install pyserial`, зупинка Ctrl+C). Файли потрапляють у `data/`.

| Документ | Про що |
|---|---|
| `firmware/activity_tracker_fw/` | Проєкт STM32CubeMX/CubeIDE: збір із датчика, препроцесинг і інференс на платі |
| `Core/Src/har_preproc.c` | ФНЧ 12 Гц, накопичення вікна 55 × 6, нормалізація |
| `Core/Src/har_model.c` | Інференс ST-IGN: власна C-реалізація, без зовнішнього рантайму |
| `Core/Inc/har_model_weights.h` | Ваги моделі, 22 949 чисел float32; генерується `validation/scripts/export_weights.py` |
| `Core/Inc/har_model_config.h` | **Згенерований** із `model_meta.json` моделі (`validation/scripts/export_firmware_config.py`): частота, вікно, класи, mean/std, ФНЧ |
| `Core/Inc/har_test_vectors.h` | 50 векторів для самоперевірки на платі (`HAR_SELFTEST 1`) |
| `Core/Src/har_out.c` | Шар виводу: один `#define` перемикає канал передачі |
| `Core/Src/har_ble.c` | Передача по BLE через STM32WB5MMG; активний лише коли обраний канал BLE |
| `tools/log.py` | Запис потоку з COM-порту в CSV |
| `data/` | Records from the sensor. `sitting_*`: mg/mdps, 7 columns. `drdytest_*`: m/s², accel only, 4 columns. New recordings: m/s² + °/s, 7 columns |

**Збірка:** STM32CubeIDE → Import → Existing Projects into Workspace → `firmware/activity_tracker_fw` (без Copy), Build, Run. Версія пакета STM32Cube_FW_U5_V1.9.0.

**Правила роботи з `.ioc`:** редагує один учасник за раз, свій код пишемо лише між `USER CODE BEGIN/END`, перед регенерацією робимо коміт.

**Статус:** модель розгорнута, прошивка збирається без помилок. Повний цикл
виконується автономно: плата читає 6 осей, фільтрує ФНЧ 12 Гц, набирає вікно
55 × 6, нормалізує і класифікує — результат іде в UART рядком `# pred`.

На платі `st_ign_realworld_imu_27hz` у float32. Її обрано після вимірювання
фактичної частоти датчика: при номінальних 26 Гц плата видає **27.45 Гц**, і
модель навчена саме на цьому числі, тож вікно з 55 відліків триває рівно 2.00 с.
Попередній варіант на 104 Гц давав фактичні 109.8 Гц і вікно 1.89 с — модель
бачила динаміку, стиснуту в часі на 5 %.

| | 27.45 Гц (зараз) | 104 Гц (було) |
|---|---|---|
| macro-F1 на test | **0.8166** | 0.8035 |
| вікно на реальній платі | **2.0036 с** | 1.8944 с |
| параметрів | 22 949 | 111 077 |
| Flash | **124 КіБ** із 2048 | 468 КіБ |
| RAM | **14 КіБ** із 768 | 50 КіБ |

Інференс написаний власним C-кодом (ST Edge AI Core не спрацював ні локально,
ні через хмару) і звірений із Python на всьому тестовому наборі:
**11 946 з 11 946** вікон дають той самий клас, максимальна різниця
ймовірностей 1.3·10⁻⁶.

**Конфігурація за замовчуванням:** `HAR_SELFTEST 0`, `HAR_STREAM_CSV 0` —
робочий режим інференсу без потоку CSV. Для збору даних увімкни
`HAR_STREAM_CSV 1`; після будь-якої зміни моделі — `HAR_SELFTEST 1`,
очікуваний результат `# selftest match=50/50`.

### Куди плата віддає дані

Увесь вивід — передбачення, рядки стану, `printf` — проходить через
`Core/Src/har_out.c`. Канал обирається одним `#define` у `Core/Inc/har_out.h`:

```c
#define HAR_OUT_PORT  HAR_OUT_STLINK   // типово: USART1 -> ST-Link -> USB
#define HAR_OUT_PORT  HAR_OUT_UART4    // UART4 -> зовнішній UART-модуль
#define HAR_OUT_PORT  HAR_OUT_BLE      // Bluetooth LE, вбудований STM32WB5MMG
```

**Кабель** (`HAR_OUT_STLINK`) — дані йдуть у віртуальний COM-порт ST-Link,
дивитися через `python tools/watch.py`. Це робочий режим за замовчуванням.

**Bluetooth LE** (`HAR_OUT_BLE`) — через вбудований модуль **STM32WB5MMG**.
На цій платі два окремі бездротові чипи: EMW3080 робить Wi-Fi, а BLE —
саме STM32WB5MMG. Головний мікроконтролер керує ним AT-командами по UART4
на 9600 бод; протокол реалізує компонент ST `stm32wb_at`, а наша обв'язка
лежить у `Core/Src/har_ble.c`. Рядки йдуть BLE-сповіщеннями, по 64 байти
максимум — наш `# pred` займає близько 35.

Щоб це запрацювало, потрібні **дві разові дії** (докладно — у шапці
`Core/Inc/har_ble.h`):

1. Додати в проєкт компонент [stm32wb_at](https://github.com/STMicroelectronics/stm32-wb-at)
   у `Drivers/BSP/Components/stm32wb_at/` і прописати цю теку в Include paths.
2. Прошити сам модуль STM32WB5MMG — з заводу він порожній. Потрібні FUS,
   BLE-стек і застосунок `BLE_AT_Server` із пакета STM32Cube_FW_WB,
   заливаються через STM32CubeProgrammer зовнішнім ST-LINK на роз'єм CN5.

Поки крок 1 не зроблено, `har_ble.c` компілюється в порожнечу і прошивка
збирається як звичайно — нічого не ламається.

**Зовнішній модуль** (`HAR_OUT_UART4`) — запасний шлях, якщо з вбудованим не
складеться: HC-05 або HM-10 на ніжки PC10/PC11, 115200. Для ноутбука він
виглядає звичайним COM-портом, тож `tools/watch.py` працює без змін.

Варто врахувати: Bluetooth доносить дані до пристрою поруч, а не до сервера.
Якщо потрібен сервер, прямий шлях — Wi-Fi модуля EMW3080, драйвер `mx_wifi`
від ST.

**Що ще не зроблено:****Що ще не зроблено:** прошивка з моделлю 27.45 Гц **не заміряна на платі** —
її треба залити й перевірити самотестом. Історичні вимірювання 104-герцового
варіанта лежать у `validation/board_logs/104hz_historical/`.

Перевірки, метрики, графіки — у теці [validation/](validation/); обґрунтування
вибору моделі — у звіті `model_selection_report.pdf`, який генерується командою
`python -m validation.scripts.report_pdf` і лягає поза репозиторієм.

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
