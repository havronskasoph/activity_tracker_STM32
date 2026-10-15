# activity_tracker_STM32

Трекер фізичної активності на STM32: плата читає 3-осьовий акселерометр і класифікує
активність нейромережею безпосередньо на мікроконтролері.

Розпізнавані класи: `Stationary`, `Walking`, `Jogging`, `Biking`.

Платформа — B-U585I-IOT02A (STM32U585AIIxQ).

## Прошивка і дані з датчика

Плата читає акселерометр ISM330DHCX по I2C і виводить потік у форматі, який очікує модель `st_ign_wl_24`. Вивід у ПК іде через UART (ST-LINK Virtual COM Port).

| Параметр | Значення |
|---|---|
| Датчик | ISM330DHCX, I2C2, адреса 0x6B (перевірка через WHO_AM_I) |
| Режим | ODR 26 Гц, ±4 g, читання за сигналом data-ready |
| Формат виводу | `timestamp_ms,ax,ay,az` |
| Одиниці | м/с² (мг × 0,00980665), гравітація в сигналі, без гіроскопа |
| Канал | USART1, 115200 8N1, `printf` перенаправлено на UART |

Запис потоку в CSV: `python tools/log.py COM3 <клас> <людина>` (потрібен `pip install pyserial`, зупинка Ctrl+C). Файли потрапляють у `data/`.

| Документ | Про що |
|---|---|
| `firmware/activity_tracker_fw/` | Проєкт STM32CubeMX/CubeIDE (код датчика в `Core/Src/main.c`, драйвер `ism330dhcx_reg.*`) |
| `tools/log.py` | Запис потоку з COM-порту в CSV |
| `data/` | Записи з датчика (старі файли: mg, 7 колонок з гіроскопом; нові: м/с², 4 колонки) |

**Збірка:** STM32CubeIDE → Import → Existing Projects into Workspace → `firmware/activity_tracker_fw` (без Copy), Build, Run. Версія пакета STM32Cube_FW_U5_V1.9.0.

**Правила роботи з `.ioc`:** редагує один учасник за раз, свій код пишемо лише між `USER CODE BEGIN/END`, перед регенерацією робимо коміт.

**Статус:** датчик, UART і запис працюють на платі. Далі: перевірка точної частоти 26 Гц, буфер на 24 відліки й інтеграція моделі.

## ML-частина

Використовується готова модель `st_ign` (варіант `st_ign_wl_24`) з офіційного
[STM32 AI Model Zoo](https://github.com/STMicroelectronics/stm32ai-modelzoo) — власна модель
не навчалася. Проведено офіційну оцінку: **91.78%** на публічному датасеті WISDM і **88.83%**
на demo-семплі `mobility_v1`. Визначено всі параметри збору даних, потрібні прошивці.

| Документ | Про що |
|---|---|
| [ml/README.md](ml/README.md) | Опис моделі, встановлення оточення, запуск оцінки |
| [ml/SENSOR_PARAMS.md](ml/SENSOR_PARAMS.md) | **Параметри сенсора для прошивки** — ODR 26 Hz, ±4 g, вікно 24 відліки без перекриття |
| [ml/results/RESULTS.md](ml/results/RESULTS.md) | Точність, confusion matrix, відкриті питання |

Датасети й клони репозиторіїв STMicroelectronics у git не зберігаються — як їх отримати,
описано в [ml/README.md](ml/README.md).
