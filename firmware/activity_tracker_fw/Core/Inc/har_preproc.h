/* Препроцесинг даних датчика перед інференсом моделі активності.
 *
 * Робить рівно те, що зроблено з навчальними даними, і нічого понад те:
 *   1. ФНЧ 25 Гц (Баттерворт 4-го порядку, каскад біквадів) на всі 6 каналів;
 *   2. накопичення вікна 208 x 6 з кроком 104 відліки (перекриття 50 %);
 *   3. нормалізацію (x - mean) / std статистиками з train.
 *
 * Навіщо ФНЧ: датасет RealWorld записаний на 50 Гц, тому реального сигналу
 * вище 25 Гц у навчальних даних немає. Датчик на 104 Гц туди шумить, і без
 * фільтра модель отримує смугу, якої ніколи не бачила.
 *
 * Усі константи — з har_model_config.h, який генерується з датасету
 * (har-dataset/scripts/export_firmware_constants.py). Руками не правити.
 *
 * Модуль не залежить від HAL і не виділяє пам'ять: його можна зібрати і
 * прогнати на ПК (див. har-dataset/tests/test_har_preproc.py).
 *
 * Типове використання в main.c:
 *
 *     har_preproc_init();
 *     ...
 *     float s[HAR_CHANNELS] = { ax, ay, az, gx, gy, gz };   // g і dps
 *     if (har_preproc_push(s)) {
 *         float *win = har_preproc_window();                // 208 x 6, [t][c]
 *         har_preproc_normalize(win);
 *         // -> подати win у модель
 *     }
 */
#ifndef HAR_PREPROC_H
#define HAR_PREPROC_H

#include <stdint.h>

#include "har_model_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Скидає стан фільтра і вікно. Викликати один раз після старту датчика. */
void har_preproc_init(void);

/* Фільтрує один відлік (6 каналів). in і out можуть збігатися. */
void har_preproc_filter(const float in[HAR_CHANNELS], float out[HAR_CHANNELS]);

/* Фільтрує відлік і кладе у вікно.
 * Повертає 1, коли зібране чергове повне вікно (тоді har_preproc_window()
 * містить 208 x 6 відліків у порядку [час][канал]), інакше 0. */
int har_preproc_push(const float sample[HAR_CHANNELS]);

/* Те саме, але з урахуванням пропущених відліків — саме це треба викликати
 * у головному циклі, бо датчик час від часу обганяє обробку.
 *
 * Правило точно таке, як у препроцесингу датасету:
 *   missed = 0                     звичайний відлік;
 *   missed <= HAR_MAX_GAP_SAMPLES  провал добивається лінійною інтерполяцією,
 *                                  щоб вікно лишалося на рівній часовій сітці;
 *   missed більше за поріг         вікно і стан фільтра скидаються — вікно
 *                                  НІКОЛИ не перетинає великий розрив.
 *
 * Повертає 1, якщо під час обробки зібралося повне вікно. */
int har_preproc_push_missed(const float sample[HAR_CHANNELS], uint32_t missed);

/* Примусово почати вікно з нуля (скидає і стан фільтра, і накопичене вікно).
 * Викликати після перезапуску датчика чи будь-якої паузи в потоці. */
void har_preproc_restart(void);

/* Вікно, зібране останнім успішним har_preproc_push().
 * Дійсне до наступного push, який поверне 1. */
float *har_preproc_window(void);

/* Останній відлік після ФНЧ — те саме, що пішло у вікно.
 * Потрібен, щоб логувати в CSV рівно те, що бачить модель. */
const float *har_preproc_last(void);

/* Нормалізація (x - mean) / std на місці. Розмір — HAR_WINDOW_SAMPLES рядків. */
void har_preproc_normalize(float *window);

/* Скільки відліків накопичено з моменту старту (діагностика). */
uint32_t har_preproc_sample_count(void);

#ifdef __cplusplus
}
#endif

#endif /* HAR_PREPROC_H */
