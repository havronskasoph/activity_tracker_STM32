/* ЗГЕНЕРОВАНО validation/scripts/export_firmware_config.py — не редагувати руками.
 *
 * Джерело: model.keras, архітектура st_ign
 * Усі числа взяті з model_meta.json моделі, тому заголовок і модель
 * не можуть розійтися.
 *
 * Формат входу: 27.45 Гц, вікно 55 x 6, канали ax, ay, az, gx, gy, gz, acc у g, gyro у dps.
 */
#ifndef HAR_MODEL_CONFIG_H
#define HAR_MODEL_CONFIG_H

/* ── Формат входу моделі ─────────────────────────────────────────── */
#define HAR_FS_HZ            27.45f
#define HAR_CHANNELS         6
#define HAR_WINDOW_SAMPLES   55      /* 2.00 с */
#define HAR_HOP_SAMPLES      27      /* перекриття 51 % */
#define HAR_MAX_GAP_SAMPLES  14      /* 0.5 с: більший розрив рве вікно */
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
/* Баттерворт 4-го порядку, зріз 12 Гц при 27.45 Гц,
 * каскад біквадів (SOS). Частота Найквіста 13.72 Гц.
 * Призначення: привести смугу сигналу з датчика до тієї, яку модель
 * бачила в навчальних даних. */
#define HAR_LPF_HZ           12.00f
#define HAR_LPF_ORDER        4
#define HAR_LPF_SECTIONS     2

/* {b0, b1, b2, a1, a2} на секцію; a0 нормалізований до 1. */
#define HAR_LPF_SOS { \
    {+5.945940043e-01f, +1.189188009e+00f, +5.945940043e-01f, +1.362058372e+00f, +4.755963524e-01f}, \
    {+1.000000000e+00f, +2.000000000e+00f, +1.000000000e+00f, +1.609226317e+00f, +7.433676358e-01f} \
}

/* ── Нормалізація ────────────────────────────────────────────────── */
/* (x - mean) / std, per channel, in the units above */
#define HAR_NORM_MEAN { -1.846634895e-01f, +7.162026763e-01f, +1.345153600e-01f, -1.430729389e+00f, -1.994805038e-01f, +1.124588847e+00f }
#define HAR_NORM_STD  { +4.311732054e-01f, +6.545906663e-01f, +2.648444474e-01f, +2.789819717e+01f, +7.596351624e+01f, +4.668102646e+01f }

#endif /* HAR_MODEL_CONFIG_H */
