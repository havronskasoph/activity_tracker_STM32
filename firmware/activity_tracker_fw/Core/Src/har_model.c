/* Реалізація інференсу ST-IGN. Див. har_model.h.
 *
 * Мережа крихітна й повністю відома, тому вона порахована тут напряму, без
 * зовнішнього рантайму. Ваги — у har_model_weights.h, згенерованому з
 * ml/models/st_ign_var2_104hz/model.keras.
 *
 * Шари, у порядку виконання:
 *   Conv2D(24, (16,1), valid)  ядро йде вздовж часу, однакове для всіх 6 каналів
 *   ReLU
 *   MaxPool((3,1))
 *   Flatten                    порядок [час][канал][фільтр], як у Keras
 *   Dense(12)
 *   Dense(5) + softmax
 *
 * Згортка, ReLU і пулінг злиті в один прохід: для кожного виходу пулінга
 * рахуються рівно три позиції згортки й береться максимум. ReLU монотонний,
 * тому max(relu(a), relu(b)) == relu(max(a, b)) — застосовуємо його раз.
 * Завдяки цьому повний вихід згортки (193 x 6 x 24 = 109 КіБ) не зберігається,
 * у пам'яті живе лише сплющений буфер 9216 float = 36 КіБ.
 */
#include "har_model.h"

#include <math.h>
#include <stddef.h>

#if HAR_MODEL_DEPLOYED
#include "har_model_weights.h"
#endif

static const char *const class_names[HAR_CLASS_COUNT] = { HAR_CLASS_LIST };

const char *har_model_class_name(int cls)
{
	if (cls < 0 || cls >= HAR_CLASS_COUNT) {
		return "?";
	}
	return class_names[cls];
}

const char *har_model_status_str(har_model_status_t st)
{
	switch (st) {
	case HAR_MODEL_OK:           return "ok";
	case HAR_MODEL_NOT_DEPLOYED: return "not deployed";
	case HAR_MODEL_INIT_FAILED:  return "init failed";
	case HAR_MODEL_RUN_FAILED:   return "run failed";
	default:                     return "?";
	}
}

#if HAR_MODEL_DEPLOYED

/* Єдиний робочий буфер: вихід пулінга у сплющеному вигляді. */
static float flat[HAR_W_FLAT];
static int ready;

int har_model_available(void)
{
	return ready;
}

har_model_status_t har_model_init(void)
{
	/* Перевіряємо, що згенеровані ваги описують ту саму форму, яку чекає
	   препроцесинг. Розбіжність означала б, що заголовки з різних прогонів. */
	if (HAR_W_TIME != HAR_WINDOW_SAMPLES || HAR_W_CHANNELS != HAR_CHANNELS
	    || HAR_W_CLASSES != HAR_CLASS_COUNT) {
		ready = 0;
		return HAR_MODEL_INIT_FAILED;
	}
	ready = 1;
	return HAR_MODEL_OK;
}

har_model_status_t har_model_predict(const float *window,
                                     float probs[HAR_CLASS_COUNT],
                                     int *top_class)
{
	float local[HAR_CLASS_COUNT];
	float *out = (probs != NULL) ? probs : local;
	float hidden[HAR_W_HIDDEN];

	if (window == NULL) {
		return HAR_MODEL_RUN_FAILED;
	}
	if (!ready) {
		return HAR_MODEL_INIT_FAILED;
	}

	/* ── Conv2D + ReLU + MaxPool, злиті ─────────────────────────────── */
	for (int p = 0; p < HAR_W_POOL_OUT; p++) {
		for (int c = 0; c < HAR_W_CHANNELS; c++) {
			for (int f = 0; f < HAR_W_FILTERS; f++) {
				const float *w = &har_w_conv_kernel[f * HAR_W_KERNEL_T];
				float best = -INFINITY;

				for (int s = 0; s < HAR_W_POOL_T; s++) {
					const int t0 = p * HAR_W_POOL_T + s;
					const float *x = &window[t0 * HAR_W_CHANNELS + c];
					float acc = har_w_conv_bias[f];

					for (int k = 0; k < HAR_W_KERNEL_T; k++) {
						acc += x[k * HAR_W_CHANNELS] * w[k];
					}
					if (acc > best) {
						best = acc;
					}
				}
				if (best < 0.0f) {
					best = 0.0f;          /* ReLU після максимуму */
				}
				flat[(p * HAR_W_CHANNELS + c) * HAR_W_FILTERS + f] = best;
			}
		}
	}

	/* ── Dense(12) ──────────────────────────────────────────────────── */
	for (int h = 0; h < HAR_W_HIDDEN; h++) {
		hidden[h] = har_w_dense0_bias[h];
	}
	for (int i = 0; i < HAR_W_FLAT; i++) {
		const float v = flat[i];
		if (v == 0.0f) {
			continue;                     /* після ReLU нулів багато */
		}
		const float *row = &har_w_dense0[i * HAR_W_HIDDEN];
		for (int h = 0; h < HAR_W_HIDDEN; h++) {
			hidden[h] += v * row[h];
		}
	}

	/* ── Dense(5) ───────────────────────────────────────────────────── */
	for (int k = 0; k < HAR_W_CLASSES; k++) {
		out[k] = har_w_dense1_bias[k];
	}
	for (int h = 0; h < HAR_W_HIDDEN; h++) {
		const float v = hidden[h];
		const float *row = &har_w_dense1[h * HAR_W_CLASSES];
		for (int k = 0; k < HAR_W_CLASSES; k++) {
			out[k] += v * row[k];
		}
	}

	/* ── Softmax ────────────────────────────────────────────────────── */
	float mx = out[0];
	for (int k = 1; k < HAR_W_CLASSES; k++) {
		if (out[k] > mx) {
			mx = out[k];
		}
	}
	float sum = 0.0f;
	for (int k = 0; k < HAR_W_CLASSES; k++) {
		out[k] = expf(out[k] - mx);
		sum += out[k];
	}
	for (int k = 0; k < HAR_W_CLASSES; k++) {
		out[k] /= sum;
	}

	if (top_class != NULL) {
		int best = 0;
		for (int k = 1; k < HAR_W_CLASSES; k++) {
			if (out[k] > out[best]) {
				best = k;
			}
		}
		*top_class = best;
	}
	return HAR_MODEL_OK;
}

#else  /* HAR_MODEL_DEPLOYED == 0 */

int har_model_available(void)
{
	return 0;
}

har_model_status_t har_model_init(void)
{
	return HAR_MODEL_NOT_DEPLOYED;
}

har_model_status_t har_model_predict(const float *window,
                                     float probs[HAR_CLASS_COUNT],
                                     int *top_class)
{
	(void) window;
	if (probs != NULL) {
		for (int i = 0; i < HAR_CLASS_COUNT; i++) {
			probs[i] = 0.0f;
		}
	}
	if (top_class != NULL) {
		*top_class = -1;
	}
	return HAR_MODEL_NOT_DEPLOYED;
}

#endif /* HAR_MODEL_DEPLOYED */
