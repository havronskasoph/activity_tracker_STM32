# activity_tracker_STM32

Трекер фізичної активності на STM32: плата читає 3-осьовий акселерометр і класифікує
активність нейромережею безпосередньо на мікроконтролері.

Розпізнавані класи: `Stationary`, `Walking`, `Jogging`, `Biking`.

Платформа — B-U585I-IOT02A (STM32U585AIIxQ).

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
