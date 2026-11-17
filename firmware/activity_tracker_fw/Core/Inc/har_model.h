/* Інференс моделі активності — єдина точка, через яку прошивка звертається
 * до нейромережі.
 *
 * Поділ обов'язків: har_preproc.c робить ФНЧ, вікно і нормалізацію, сюди
 * приходить уже готове вікно HAR_WINDOW_SAMPLES x HAR_CHANNELS у порядку
 * [час][канал], нормалізоване статистиками з har_model_config.h.
 *
 * Модель на платі з'являється так:
 *   1. натренувати на датасеті 104 Гц -> model.keras;
 *   2. STM32Cube.AI (CubeMX -> X-CUBE-AI) згенерує network.c/.h
 *      і network_data.c/.h;
 *   3. покласти їх у проєкт і поставити HAR_MODEL_DEPLOYED 1.
 *
 * Доки HAR_MODEL_DEPLOYED == 0, прошивка збирається і працює повністю:
 * вікна накопичуються, CSV іде в UART, у рядку стану видно їх кількість.
 * Немає лише класифікації — har_model_predict() повертає HAR_MODEL_NOT_DEPLOYED.
 */
#ifndef HAR_MODEL_H
#define HAR_MODEL_H

#include "har_model_config.h"

/* 0 — мережі в проєкті немає (збирається, інференс вимкнений);
 * 1 — ваги в har_model_weights.h присутні, інференс увімкнений.
 * Можна перевизначити при збірці (-DHAR_MODEL_DEPLOYED=0) — цим користуються
 * хостові тести. */
#ifndef HAR_MODEL_DEPLOYED
#define HAR_MODEL_DEPLOYED  1
#endif

typedef enum {
	HAR_MODEL_OK           =  0,
	HAR_MODEL_NOT_DEPLOYED = -1,   /* зібрано з HAR_MODEL_DEPLOYED == 0 */
	HAR_MODEL_INIT_FAILED  = -2,   /* Cube.AI не зміг створити мережу */
	HAR_MODEL_RUN_FAILED   = -3,   /* помилка під час інференсу */
} har_model_status_t;

#ifdef __cplusplus
extern "C" {
#endif

/* Ініціалізує мережу. Викликати один раз після har_preproc_init(). */
har_model_status_t har_model_init(void);

/* 1, якщо модель готова рахувати; 0 — якщо її в прошивці немає. */
int har_model_available(void);

/* Класифікує одне нормалізоване вікно.
 *
 *   window     HAR_WINDOW_SAMPLES * HAR_CHANNELS float, [час][канал];
 *   probs      імовірності класів у порядку HAR_CLASS_* (можна NULL);
 *   top_class  індекс найімовірнішого класу (можна NULL).
 *
 * Повертає HAR_MODEL_OK лише тоді, коли probs і top_class заповнені. */
har_model_status_t har_model_predict(const float *window,
                                     float probs[HAR_CLASS_COUNT],
                                     int *top_class);

/* Назва класу з HAR_CLASS_LIST; "?" для індексу поза діапазоном. */
const char *har_model_class_name(int cls);

/* Короткий текст статусу — для рядка стану в UART. */
const char *har_model_status_str(har_model_status_t st);

#ifdef __cplusplus
}
#endif

#endif /* HAR_MODEL_H */
