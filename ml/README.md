# 6-axis HAR models (accelerometer + gyroscope)

ST-IGN activity classifiers trained on the RealWorld HAR upper-arm recordings. The model accepts
2-second windows of `ax, ay, az, gx, gy, gz`; acceleration must be in **g**, gyroscope in **°/s**.
`HARClassifier` applies the per-model training mean and standard deviation internally.

## Trained models

All results below use held-out subjects. Choose a model whose sample rate matches the input stream.

| Model folder | Rate | Window / stride | Params | Test accuracy | Test macro-F1 | Val macro-F1 |
|---|---:|---:|---:|---:|---:|---:|
| `models/st_ign_realworld_imu_27hz/` | **27.45 Hz** | 55 / 27 | 22,949 | 0.838 | 0.817 | 0.809 |
| `models/st_ign_realworld_imu/` | 52 Hz | 104 / 52 | 50,597 | 0.820 | 0.799 | 0.773 |
| `models/st_ign_var2_104hz/` | **104 Hz** | 208 / 104 | 111,077 | 0.820 | 0.803 | 0.766 |

The current firmware requests 26 Hz and was measured at 27.45 Hz, so use
`st_ign_realworld_imu_27hz` with current board recordings. The 104 Hz model is for a 104 Hz input
stream and is not a direct match for the current firmware. Resampling a 27.45 Hz board recording to
104 Hz cannot recover missing signal information; use it only for offline experiments with that
limitation understood.

The 104 Hz model was trained for 23 epochs (best checkpoint: epoch 8; 199 seconds). Validation
accuracy / macro-F1 are **0.770 / 0.766**; test accuracy / macro-F1 are **0.820 / 0.803**. Test F1
by class:

| Model | Lying | Stationary | Walking | Running | Stairs |
|---|---:|---:|---:|---:|---:|
| 27.45 Hz | 0.954 | 0.961 | 0.503 | 0.928 | 0.737 |
| 52 Hz | 0.985 | 0.971 | 0.420 | 0.935 | 0.682 |
| 104 Hz | 0.969 | 0.964 | 0.468 | 0.935 | 0.682 |

Walking and Stairs remain the weakest classes. The reports, confusion matrices, training curves, and
exact configs are kept beside each model. The 104 Hz results are a baseline from one seeded run, not
a performance guarantee on the device.

## Dataset and 104 Hz preprocessing

The 52 Hz models use the pinned, pre-windowed RealWorld upper-arm dataset downloaded by the trainer.
The 104 Hz run uses prepared files in `data/har_var2/` (gitignored): `train.npz`, `val.npz`,
`test.npz`, `norm_stats.json`, and `label_map.json`. These contain 208 × 6 windows, 50% overlap,
five classes, physical units, and subject-exclusive train/validation/test splits. The source dataset
checkout and preprocessing scripts currently live locally at `data/har_var2_source/`; both it and
the prepared data are excluded from git. See its README for the RealWorld citation, download and
preprocessing details. The data is resampled from approximately 50 Hz to 104 Hz for format alignment;
this does not create real signal content above the source's approximately 25 Hz Nyquist limit.

## Setup

Use Python 3.12 and install the ML dependencies:

```bash
cd ml
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-har.txt
```

## Inference

Run commands from `ml/`. The default classifier is the 52 Hz model; pass a model directory explicitly
to select another variant.

```python
from har import HARClassifier, board_to_model_units

clf = HARClassifier.load("models/st_ign_var2_104hz")
print(clf.sample_rate_hz, clf.window_samples, clf.stride_samples)  # 104.0, 208, 104

# window is (208, 6), sampled at 104 Hz, in g and °/s, channel order ax,ay,az,gx,gy,gz
pred = clf.predict(window)
print(pred.label, pred.confidence)

# Continuous 104 Hz stream: (M, 6); windows every 104 samples
preds = clf.predict_stream(samples)

# Board logs currently have acceleration in m/s² and gyro in °/s
samples_model_units = board_to_model_units(samples_from_board)
```

For the current 27.45 Hz board, select the matching model:

```python
clf = HARClassifier.load("models/st_ign_realworld_imu_27hz")
```

Classify a CSV recording from `tools/log.py` (columns `timestamp_ms,ax,ay,az,gx,gy,gz`):

```bash
python -m har.predict ../data/<recording>.csv \
  --model-dir models/st_ign_realworld_imu_27hz
```

`--resample` interpolates a recording to the selected model's rate. It is useful for small timing
differences, but cannot restore information absent from a lower-rate recording. The 104 Hz model
expects 208 samples per 2-second window and advances by 104 samples.

## Train

```bash
cd ml
python -m har.train --download
python -m har.train --config configs/st_ign_realworld_imu_27hz.yaml
python -m har.train --config configs/st_ign_var2_104hz.yaml
python -m har.train --output-dir models/experiment1
```

`--download` fetches the pre-windowed 52 Hz dataset into `data/realworld_imu/`. The 104 Hz config
reads the prepared local files at `data/har_var2/`; it uses `sample_rate_hz: null` to retain their
native rate. To regenerate those files, use the preprocessing checkout at `data/har_var2_source/`
and follow its README. `ml/data/` is gitignored, so datasets and that checkout are not included in
the repository.

Training uses balanced class weights and selects the best checkpoint by validation loss. Each run
writes `model.keras`, `model_meta.json` (class/channel mapping, units, sample rate, window and
normalization mean/std), `config.yaml`, `history.csv`, training curves, and validation/test metrics,
reports, and confusion matrices.

## Firmware input contract

For the 104 Hz model, the input stream must match all of these details:

| Setting | Required value |
|---|---|
| Sampling rate | 104 Hz for accelerometer and gyroscope |
| Window / stride | 208 samples / 104 samples (2 seconds / 50% overlap) |
| Channel order | `ax, ay, az, gx, gy, gz` |
| Units | acceleration in g; gyroscope in °/s |
| Normalization | `(x - mean) / std` using the 104 Hz model's `model_meta.json` |
| Gravity | retain it; do not subtract the static acceleration component |
| Input filtering | low-pass at 25 Hz before inference |
| Placement | upper arm, above the elbow, as in the dataset |

The source recordings are approximately 50 Hz, so filtering the 104 Hz board stream at 25 Hz keeps
the input bandwidth consistent with training. The current firmware is 27.45 Hz and does not yet
meet this 104 Hz contract. On-device deployment also needs model conversion/quantization and a RAM /
Flash budget check; the `.keras` model is a training/inference artifact, not a firmware binary.

## Files

```
ml/
├── configs/                 training configs, including st_ign_var2_104hz.yaml
├── har/                     loader, ST-IGN, training, evaluation, inference and CSV prediction
├── models/                  trained models and reports (including st_ign_var2_104hz/)
└── data/                    local datasets and preprocessing checkout (gitignored)
```
