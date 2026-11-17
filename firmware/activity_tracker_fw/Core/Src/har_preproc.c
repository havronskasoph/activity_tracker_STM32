#include "har_preproc.h"

#include <string.h>

/* Коефіцієнти і розміри — з har_model_config.h (генерується з датасету). */
static const float sos[HAR_LPF_SECTIONS][5] = HAR_LPF_SOS;
static const float norm_mean[HAR_CHANNELS] = HAR_NORM_MEAN;
static const float norm_std[HAR_CHANNELS] = HAR_NORM_STD;

/* Стан біквадів у формі Direct Form II transposed: по дві змінні на секцію
   і канал. DF2T стійкіша до накопичення похибки у float32, ніж DF1. */
static float state[HAR_LPF_SECTIONS][HAR_CHANNELS][2];

/* Кільцевий буфер відліків і лінійна копія, яку віддаємо назовні.
   10 КБ на обидва при 208 x 6 float — на STM32U585 (786 КБ SRAM) це дрібниця,
   зате назовні йде суцільний масив, який модель читає без зайвих перестановок. */
static float ring[HAR_WINDOW_SAMPLES][HAR_CHANNELS];
static float window_out[HAR_WINDOW_SAMPLES][HAR_CHANNELS];

static const float *last_filtered;  /* останній відлік після ФНЧ */

/* Останній СИРИЙ відлік: з нього добиваються пропущені (див. push_missed). */
static float prev_raw[HAR_CHANNELS];
static uint8_t have_prev;

/* Інтерполяція провалу не повинна перекрити межу вікна більше одного разу —
   інакше готове вікно загубилося б. Поки поріг менший за крок, це гарантовано. */
#if HAR_MAX_GAP_SAMPLES >= HAR_HOP_SAMPLES
#error "HAR_MAX_GAP_SAMPLES має бути меншим за HAR_HOP_SAMPLES"
#endif

static uint16_t ring_head;      /* куди писати наступний відлік */
static uint16_t ring_filled;    /* скільки відліків уже в буфері (до WINDOW) */
static uint16_t since_window;   /* відліків від останнього виданого вікна */
static uint32_t total_samples;

void har_preproc_init(void)
{
	memset(state, 0, sizeof(state));
	memset(ring, 0, sizeof(ring));
	last_filtered = ring[0];
	memset(prev_raw, 0, sizeof(prev_raw));
	have_prev = 0;
	ring_head = 0;
	ring_filled = 0;
	since_window = 0;
	total_samples = 0;
}

void har_preproc_filter(const float in[HAR_CHANNELS], float out[HAR_CHANNELS])
{
	for (int c = 0; c < HAR_CHANNELS; c++) {
		float x = in[c];

		for (int s = 0; s < HAR_LPF_SECTIONS; s++) {
			const float b0 = sos[s][0], b1 = sos[s][1], b2 = sos[s][2];
			const float a1 = sos[s][3], a2 = sos[s][4];
			float *z = state[s][c];

			const float y = b0 * x + z[0];
			z[0] = b1 * x - a1 * y + z[1];
			z[1] = b2 * x - a2 * y;
			x = y;
		}
		out[c] = x;
	}
}

int har_preproc_push(const float sample[HAR_CHANNELS])
{
	har_preproc_filter(sample, ring[ring_head]);
	last_filtered = ring[ring_head];
	memcpy(prev_raw, sample, sizeof(prev_raw));
	have_prev = 1;

	ring_head = (uint16_t) ((ring_head + 1u) % HAR_WINDOW_SAMPLES);
	if (ring_filled < HAR_WINDOW_SAMPLES) {
		ring_filled++;
	}
	if (total_samples < 0xFFFFFFFFu) {
		total_samples++;
	}
	since_window++;

	/* Перше вікно — щойно буфер заповнився, далі кожні HAR_HOP_SAMPLES.
	   До цього моменту через фільтр пройшло щонайменше 208 відліків, тож його
	   перехідний процес уже минув і у вікно не потрапляє. */
	if (ring_filled < HAR_WINDOW_SAMPLES || since_window < HAR_HOP_SAMPLES) {
		return 0;
	}
	since_window = 0;

	/* Розгортаємо кільце в суцільний масив: найстаріший відлік — перший. */
	const uint16_t tail = ring_head;            /* він же найстаріший елемент */
	const uint16_t first = (uint16_t) (HAR_WINDOW_SAMPLES - tail);
	memcpy(window_out, ring[tail], (size_t) first * HAR_CHANNELS * sizeof(float));
	if (tail != 0) {
		memcpy(window_out[first], ring[0],
		       (size_t) tail * HAR_CHANNELS * sizeof(float));
	}
	return 1;
}

void har_preproc_restart(void)
{
	/* Стан фільтра теж скидаємо: після паузи він тримає «хвіст» старого
	   сигналу, і перші відліки нового вікна були б ним зіпсовані. */
	memset(state, 0, sizeof(state));
	ring_filled = 0;
	since_window = 0;
	have_prev = 0;
}

int har_preproc_push_missed(const float sample[HAR_CHANNELS], uint32_t missed)
{
	int ready = 0;

	if (missed > (uint32_t) HAR_MAX_GAP_SAMPLES) {
		/* Великий провал: добивати його інтерполяцією означало б вигадати
		   рух, якого не було. Починаємо вікно з чистого аркуша. */
		har_preproc_restart();
	} else if (missed > 0u && have_prev) {
		/* Малий провал: відновлюємо пропущені відліки по прямій між
		   попереднім і новим — так само, як препроцесинг датасету
		   інтерполює сирі дані на рівну сітку. */
		for (uint32_t k = 1u; k <= missed; k++) {
			float filled[HAR_CHANNELS];
			const float w = (float) k / (float) (missed + 1u);

			for (int c = 0; c < HAR_CHANNELS; c++) {
				filled[c] = prev_raw[c] + (sample[c] - prev_raw[c]) * w;
			}
			ready |= har_preproc_push(filled);
		}
	}

	ready |= har_preproc_push(sample);
	return ready;
}

float *har_preproc_window(void)
{
	return &window_out[0][0];
}

const float *har_preproc_last(void)
{
	return last_filtered;
}

void har_preproc_normalize(float *window)
{
	for (int t = 0; t < HAR_WINDOW_SAMPLES; t++) {
		float *row = window + (size_t) t * HAR_CHANNELS;
		for (int c = 0; c < HAR_CHANNELS; c++) {
			row[c] = (row[c] - norm_mean[c]) / norm_std[c];
		}
	}
}

uint32_t har_preproc_sample_count(void)
{
	return total_samples;
}
