# 6-axis HAR model (accelerometer + gyroscope)

Self-contained training and inference for an activity classifier that uses all six IMU axes.
Everything lives in `ml/`; no clone of the ST Model Zoo is needed.

| | |
|---|---|
| Model | ST-IGN (from `stm32ai-modelzoo-services`, SLA0044) |
| Input | 2.0 s windows × 6 axes, order `ax, ay, az, gx, gy, gz` |
| Units | accelerometer in **g**, gyroscope in **°/s**, raw (normalization is done by the model wrapper) |
| Classes | `Lying, Stationary, Walking, Running, Stairs` |
| Data | [RealWorld HAR, upper arm](https://github.com/alinaytsk/har-realworld-dataset) @ `6f24dcd`, 52 Hz, split by person: 10 train / 2 val / 3 test |

## Trained models

Two quick CPU runs (under 30 s each, early-stopped), same data and settings except the sample rate:

| Model folder | Rate | Window | Params | Test acc. | Test macro-F1 | Val macro-F1 |
|---|---|---|---|---|---|---|
| `models/st_ign_realworld_imu_27hz/` | **27.45 Hz** (board) | 55 × 6 | 22,949 | 0.838 | 0.817 | 0.809 |
| `models/st_ign_realworld_imu/` | 52 Hz (dataset) | 104 × 6 | 50,597 | 0.820 | 0.799 | 0.773 |

**Use the 27.45 Hz model with the current firmware.** It matches the rate the board actually
samples at (26 Hz requested, 27.45 Hz measured). The two models score about the same; with one
run each, the difference is within run-to-run noise.

Test F1 per class:

| Model | Lying | Stationary | Walking | Running | Stairs |
|---|---|---|---|---|---|
| 27.45 Hz | 0.954 | 0.961 | **0.503** | 0.928 | 0.737 |
| 52 Hz | 0.985 | 0.971 | **0.420** | 0.935 | 0.682 |

Walking vs. Stairs is the weak spot in both: most walking windows of the test subjects are
predicted as Stairs. Treat these models as baselines; they have not been tuned.
Each folder has confusion matrices, training curves and full reports.

## Setup

```bash
cd ml
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-har.txt
```

## Use the model (teammates start here)

```python
from har import HARClassifier, board_to_model_units

clf = HARClassifier.load("models/st_ign_realworld_imu_27hz")   # no argument: the 52 Hz model
print(clf.sample_rate_hz, clf.window_samples)                  # 27.45, 55
pred = clf.predict(window)            # window: np.ndarray (55, 6), accel in g, gyro in deg/s
print(pred.label, pred.confidence)    # e.g. "Running", 0.97
print(pred.probabilities)             # {"Lying": ..., "Stationary": ..., ...}

preds = clf.predict_batch(windows)    # (N, 55, 6) -> list of Prediction
preds = clf.predict_stream(samples)   # (M, 6) continuous recording, 55-sample windows every 27 samples

samples_g = board_to_model_units(samples_from_board)   # firmware prints accel in m/s^2 -> g
```

Run it from the `ml/` folder (or add `ml/` to `PYTHONPATH`).

Classify a board recording made with `tools/log.py` (7 columns: `timestamp_ms,ax,ay,az,gx,gy,gz`):

```bash
python -m har.predict ../data/<recording>.csv --model-dir models/st_ign_realworld_imu_27hz
python -m har.predict ../data/<recording>.csv --model-dir ... --resample   # board rate differs from the model's
```

The window size, stride and sample rate always come from the model's `model_meta.json`.

## Train

```bash
cd ml
python -m har.train --download                      # first run: fetches ~125 MB into ml/data/ (gitignored)
python -m har.train --max-minutes 10                # override the wall-clock cap
python -m har.train --output-dir models/experiment1 # keep the shipped model untouched
python -m har.train --config configs/st_ign_realworld_imu_27hz.yaml   # board-rate model
```

Settings are in `configs/st_ign_realworld_imu.yaml` (52 Hz) and `configs/st_ign_realworld_imu_27hz.yaml`.

**Training sample rate.** `dataset.sample_rate_hz` sets the rate the model is trained for
(`null` = the dataset's native 52 Hz; only lower rates are possible). The dataset's windows overlap by
50 %, so the loader stitches them back into continuous recordings, resamples each recording with an
anti-aliasing filter, and cuts new 2.0 s windows with 50 % overlap. That's the same thing the board
does on its live stream, so no window-edge artifacts. Normalization mean/std are recomputed at the
new rate and saved in `model_meta.json`. If the firmware rate changes, set this value to the
**measured** rate and retrain. Losses use balanced class weights
(Stationary and Stairs have about 2× the windows). The best epoch by `val_loss` is saved.

Each run writes `model.keras`, `model_meta.json` (classes, channels, units, rate, window,
normalization mean/std), `history.csv`, `training_curves.png`, and for val and test:
`*_metrics.json` (accuracy, macro/weighted F1, per-class precision/recall/F1),
`*_report.txt` and `*_confusion_matrix.{csv,png}`.

## Firmware vs. model

| | 27.45 Hz model | Firmware now |
|---|---|---|
| Sample rate | 27.45 Hz | 26 Hz requested, 27.45 Hz measured ✓ |
| Accelerometer units | g | m/s² (use `board_to_model_units`, or change `put_ms2` scaling) |
| Gyroscope units | °/s | °/s ✓ |
| Channel order | ax, ay, az, gx, gy, gz | same ✓ |
| Placement | upper arm, above the elbow | — |

The 27.45 Hz rate was measured with the accelerometer only. Re-measure it once the gyro firmware
runs on the board. If it differs, retrain with that value. On the MCU, the same `mean`/`std` from
`model_meta.json` must be applied before inference.

## Open questions

- [ ] **Quantization.** Models are FLOAT32 `.keras` only. Decide whether int8 is needed, and what
      RAM/Flash budget the model gets on the STM32U585.
- [ ] **Smoothing across windows.** One window is 2 s. Check on real board recordings how stable a
      single-window prediction is, and whether to vote or average over several consecutive windows.
- [ ] **Walking vs. Stairs.** Most test-subject walking windows are predicted as Stairs.
- [ ] **Real board data.** No recording from the board has been classified yet.

## Files

```
ml/
├── configs/
│   ├── st_ign_realworld_imu.yaml        52 Hz training config
│   └── st_ign_realworld_imu_27hz.yaml   board-rate training config
├── har/
│   ├── data.py         download + load the dataset (pinned commit), sanity checks, resampling
│   ├── model.py        ST-IGN (adapted from the ST Model Zoo)
│   ├── train.py        training CLI
│   ├── evaluate.py     metrics, confusion matrices, training curves
│   ├── inference.py    HARClassifier: load, preprocess, predict
│   └── predict.py      CLI for tools/log.py recordings
├── models/st_ign_realworld_imu/        52 Hz model + reports (versioned)
├── models/st_ign_realworld_imu_27hz/   27.45 Hz model + reports (versioned)
└── data/                               dataset (not versioned)
```

What was not taken from the ST fork: its CSV loader (`realworld_imu.py`) and `imu_transfer.py`.
The dataset repo already provides windowed, subject-split data, and the transfer helper only
supports the 24-sample model, not 104-sample windows.

Earlier work used ST's ready-made 3-axis model `st_ign_wl_24` without training it
(91.78 % on WISDM, 88.83 % on the `mobility_v1` demo sample). Its docs and evaluation were removed
from this folder; they are in git history at commit `cd24ea8`.
