# ML-частина: Human Activity Recognition

Розпізнавання активності людини за даними 3-осьового акселерометра. Використовується готова
модель з офіційного STM32 AI Model Zoo — власна модель не навчалася. Робота полягала у виборі
моделі, перевірці її точності та визначенні параметрів збору даних для прошивки.

| Параметр | Значення |
|---|---|
| Назва | `st_ign` — CNN за Ignatov, модифікація від STMicroelectronics (префікс `st_`) |
| Варіант | `st_ign_wl_24` (window length = 24 відліки) |
| Навчена на | `mobility_v1` — власний датасет ST, публічно недоступний |
| Вхід | `(24, 3, 1)` — 24 відліки × 3 осі акселерометра × 1 канал, FLOAT32 |
| Вихід | 4 класи: `Stationary`, `Walking`, `Jogging`, `Biking` |
| Параметрів | 3 064 |
| Формат файлу | `.keras` (FLOAT32, без квантування) |

Шлях у Model Zoo:

```
human_activity_recognition/st_ign/ST_pretrainedmodel_custom_dataset/mobility_v1/st_ign_wl_24/st_ign_wl_24.keras
```

| Репозиторій-джерело | URL |
|---|---|
| Моделі | https://github.com/STMicroelectronics/stm32ai-modelzoo |
| Скрипти (training / evaluation / deployment) | https://github.com/STMicroelectronics/stm32ai-modelzoo-services |

---

## Setup

ML-оточення живе **поза цим репозиторієм** — тут лише документація, зафіксовані версії
залежностей і результати. Клони офіційних репозиторіїв і датасети в git не додаються.

Шляхи нижче наведені для `C:\proj` — можна обрати будь-яку іншу теку, головне узгодити її
в конфігах.

### 1. Клонувати репозиторії STMicroelectronics

```bash
mkdir C:\proj
cd C:\proj
git clone https://github.com/STMicroelectronics/stm32ai-modelzoo.git
git clone https://github.com/STMicroelectronics/stm32ai-modelzoo-services.git
```

`stm32ai-modelzoo` — самі моделі (`.keras`), `stm32ai-modelzoo-services` — скрипти
training / evaluation / deployment.

### 2. Встановити Python-залежності

```bash
python -m venv C:\proj\venv
C:\proj\venv\Scripts\activate
pip install -r <шлях_до_цього_репозиторію>\ml\requirements.txt
```

[`requirements.txt`](requirements.txt) — точний зліпок оточення, на якому реально відпрацювали
обидві оцінки (`pip freeze`, 155 пакетів, Python 3.13.14). Використовуйте саме його, а не
`requirements.txt` з `stm32ai-modelzoo-services`: офіційний пінить `tensorflow==2.18.0`, для
якого немає збірок під Python 3.13.

> **Увага.** `stm32ai_main.py` імпортує обгортки **всіх** use-case репозиторію (`api/api.py`),
> тому для запуску HAR потрібні залежності й для object detection, speech enhancement тощо —
> включно з `tf2onnx`, `opencv-python`, `tensorboard`, `librosa`, `pesq`.
> Пакет `pesq` збирається з C-сирців і потребує Visual Studio Build Tools, тому
> у `ml/requirements.txt` його **немає**. Способи обходу описані в шапці самого файлу.

### 3. Датасети

#### mobility_v1 (demo-семпл) — завантажувати не треба

Уже вбудований у клон `stm32ai-modelzoo-services`:

```
C:\proj\stm32ai-modelzoo-services\human_activity_recognition\datasets\mobility_v1\
├── train.pkl
└── test.pkl
```

Це невелика підмножина (11 записів у `train.pkl`, 5 у `test.pkl`), а не повний датасет.
Повний `mobility_v1` — власність ST і публічно недоступний. Ліцензія підмножини — SLA044,
див. `human_activity_recognition/datasets/LICENSE.md`.

#### WISDM — завантажити окремо

```bash
mkdir C:\proj\datasets\wisdm
cd C:\proj\datasets\wisdm
curl -L -o WISDM_ar_latest.tar.gz https://www.cis.fordham.edu/wisdm/includes/datasets/latest/WISDM_ar_latest.tar.gz
tar -xzf WISDM_ar_latest.tar.gz --strip-components=1
```

Після розпакування має бути `WISDM_ar_v1.1_raw.txt` (приблизно 50 МБ) — для оцінки потрібен
тільки він. Якщо `--strip-components=1` не підійде до структури архіву, приберіть цей ключ
і перевірте, де опинився файл.

Сторінка датасету: https://www.cis.fordham.edu/wisdm/dataset.php, ліцензія CC BY 2.0.

> **Увага.** Завантажувач WISDM викликає `clean_csv()`, який **перезаписує вихідний
> `WISDM_ar_v1.1_raw.txt` на місці** (прибирає `;` у кінці рядків, файл зменшується приблизно
> на 2 МБ). Зробіть копію оригіналу, якщо він потрібен у первинному вигляді.

### 4. Налаштувати конфіг і запустити

Конфіг для `mobility_v1`:

```yaml
operation_mode: evaluation

dataset:
  dataset_name: mobility_v1
  class_names: [Stationary, Walking, Jogging, Biking]
  training_path: ./datasets/mobility_v1/train.pkl
  test_path: ./datasets/mobility_v1/test.pkl

model:
  model_path: ../../stm32ai-modelzoo/human_activity_recognition/st_ign/ST_pretrainedmodel_custom_dataset/mobility_v1/st_ign_wl_24/st_ign_wl_24.keras

preprocessing:
  gravity_rot_sup: true
  normalization: false
```

Для WISDM міняються **дві** секції — і `dataset`, і `model`. Модель інша: під WISDM навчена
окрема копія, у підпапці `ST_pretrainedmodel_public_dataset`, з іншим набором класів.
Якщо підставити модель `mobility_v1`, результат буде беззмістовним:

```yaml
dataset:
  dataset_name: wisdm
  class_names: [Jogging, Stationary, Stairs, Walking]
  training_path: ../../datasets/wisdm/WISDM_ar_v1.1_raw.txt

model:
  model_path: ../../stm32ai-modelzoo/human_activity_recognition/st_ign/ST_pretrainedmodel_public_dataset/WISDM/st_ign_wl_24/st_ign_wl_24.keras
```

`test_path` для WISDM не потрібен — тестова вибірка відділяється від `training_path`
автоматично.

Шляхи відносні до теки `human_activity_recognition`, з якої запускається скрипт.

```bash
cd C:\proj\stm32ai-modelzoo-services\human_activity_recognition
python stm32ai_main.py --config-path ./config_file_examples/ --config-name <ваш_конфіг>.yaml
```

Результати — точність, лог і confusion matrix — зберігаються в
`tf/src/experiments_outputs/<дата-час>/`.

---

## Решта документації

| Файл | Про що |
|---|---|
| [SENSOR_PARAMS.md](SENSOR_PARAMS.md) | **Параметри для прошивки сенсора** — ODR, full scale, одиниці, орієнтація осей, розмір вікна. Головний документ для firmware |
| [results/RESULTS.md](results/RESULTS.md) | Результати точності, confusion matrix, список TODO |
| [requirements.txt](requirements.txt) | Зафіксоване Python-оточення |
