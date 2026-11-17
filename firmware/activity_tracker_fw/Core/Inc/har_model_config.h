/* ЗГЕНЕРОВАНО АВТОМАТИЧНО — не редагувати руками.
 *
 * Джерело: har-dataset/config.yaml + data/processed/norm_stats.json
 * Перегенерувати: python scripts/export_firmware_constants.py
 *
 * Ці константи описують рівно той формат даних, на якому навчена модель:
 * 104 Гц, вікно 208 x 6, канали ax, ay, az, gx, gy, gz, acc у g, gyro у dps.
 */
#ifndef HAR_MODEL_CONFIG_H
#define HAR_MODEL_CONFIG_H

/* ── Формат входу моделі ─────────────────────────────────────────── */
#define HAR_FS_HZ            104.0f
#define HAR_CHANNELS         6
#define HAR_WINDOW_SAMPLES   208      /* 2.00 с */
#define HAR_HOP_SAMPLES      104      /* перекриття 50 % */
#define HAR_MAX_GAP_SAMPLES  52      /* 0.5 с: більший розрив рве вікно */
#define HAR_ACC_UNIT         "g"
#define HAR_GYR_UNIT         "dps"

/* Порядок каналів у вікні (рядок = момент часу): */
/*   0:ax, 1:ay, 2:az, 3:gx, 4:gy, 5:gz */

/* ── Класи ───────────────────────────────────────────────────────── */
#define HAR_CLASS_COUNT      5
#define HAR_CLASS_LIST       "Lying", "Stationary", "Walking", "Running", "Stairs"

#define HAR_CLASS_LYING        0
#define HAR_CLASS_STATIONARY   1
#define HAR_CLASS_WALKING      2
#define HAR_CLASS_RUNNING      3
#define HAR_CLASS_STAIRS       4

/* ── ФНЧ перед інференсом ────────────────────────────────────────── */
/* Баттерворт 4-го порядку, зріз 25 Гц при 104 Гц, у вигляді каскаду біквадів (SOS).
 * Потрібен обов'язково: навчальні дані отримані з 50-герцового джерела,
 * тому вище 25 Гц у них сигналу немає, а датчик на платі туди шумить. */
#define HAR_LPF_HZ           25.0f
#define HAR_LPF_ORDER        4
#define HAR_LPF_SECTIONS     2

/* {b0, b1, b2, a1, a2} на секцію; a0 нормалізований до 1. */
#define HAR_LPF_SOS { \
    { +8.308933554e-02f, +1.661786711e-01f, +8.308933554e-02f, -6.282248154e-02f, +4.047772339e-02f }, \
    { +1.000000000e+00f, +2.000000000e+00f, +1.000000000e+00f, -8.737936609e-02f, +4.471934516e-01f } \
}

/* ── Нормалізація (статистики з train, НЕ перераховувати) ────────── */
/* джерело: train, 42052 вікон, учасники [1, 2, 3, 4, 5, 7, 8, 9, 11, 13] */
#define HAR_NORM_MEAN { -1.837570700e-01f, +7.177596700e-01f, +1.343726200e-01f, -1.424373270e+00f, -1.953509600e-01f, +1.123179320e+00f }
#define HAR_NORM_STD  { +4.285964400e-01f, +6.469613300e-01f, +2.637774600e-01f, +2.784046745e+01f, +7.574771118e+01f, +4.656782150e+01f }

#endif /* HAR_MODEL_CONFIG_H */
