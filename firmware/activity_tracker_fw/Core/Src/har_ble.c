/* BLE_AT_Server custom service. The board's STM32WB module must already run
 * ST's BLE_AT_Server and a compatible wireless stack. Communication uses the
 * same UART4/9600/8N1 connection as ST's B-U585I-IOT02A example.
 *
 * Custom service UUID:        0000aabb-cc7a-482a-984a-7f2ed5b3e58f
 * Notification UUID:          00003344-8e22-4541-9d4c-21edae82ed19
 *
 * Формат кожної команди звірено з офіційним драйвером ST (stm32-wb-at,
 * stm32wb_at_client.c):
 *   AT             — AT_CMD_TEST + AT_EOL, саме так його шле приклад ST
 *   BLE_SVC        — index, uuid_type, 0x%04x uuid, max_attr_record; додаткові
 *                    параметри сервер читає лише коли index >= 3
 *                    (SRV_CUSTOM_APP_SVC_OFFSET), тобто 3 — перший кастомний
 *   BLE_CHAR_ADD   — svc, char, uuid_type, 0x%04x uuid, value_len,
 *                    0x%02x props, 0x%02x sec, 0x%02x evt_mask
 *   BLE_NOTIF_VAL  — svc, char, далі 0x<hex> для кількох байтів АБО десяткове
 *                    число для одного (у ST це розгалуження val_tab_len <= 1)
 */
#include "har_ble.h"
#include "main.h"
#include <stdio.h>
#include <string.h>

#if HAR_BLE_ENABLED
extern UART_HandleTypeDef huart4;

static uint8_t ready;
static uint8_t fail_streak;
static uint8_t last_ok;         /* чи дійшла остання спроба */
static uint8_t soft_fail;       /* бітова маска необов'язкових кроків, що впали */
static uint32_t hold_until;     /* тік, до якого не пробуємо; 0 — паузи нема */
static uint32_t readv_at;       /* тік останнього поновлення реклами */

/* Останній обмін із модулем — для журналу. Пишемо сюди під час команди, а
   друкуємо вже після неї: printf у USART1 блокує на ~87 мкс на символ, і
   якби ми друкували всередині циклу прийому, то губили б байти відповіді,
   бо на UART4 немає ні перивань, ні DMA. */
static char at_reply[192];
static uint16_t at_reply_len;

#if HAR_BLE_VERBOSE
static void at_log(const char *command, uint8_t decided)
{
	char echo[72];
	uint16_t n = 0u;

	while (command[n] != '\0' && n < (sizeof(echo) - 1u)
			&& command[n] != '\r' && command[n] != '\n') {
		echo[n] = command[n];
		n++;
	}
	echo[n] = '\0';

	printf("# at> %s\r\n", echo);
	printf("# at< %s%s\r\n",
			(at_reply_len > 0u) ? at_reply : "(тишина)",
			decided ? "" : "   <-- таймаут");
}
#else
#define at_log(command, decided)   ((void) 0)
#endif

/* Wait for the command's OK or ERROR. Unsolicited events are ignored.
 * A bounded timeout ensures a missing radio never hangs the inference loop. */
static uint8_t at_command(const char *command, uint32_t timeout_ms)
{
	char line[96];
	uint16_t used = 0u;
	uint32_t start;
	uint8_t ch;
	uint8_t result = 1u;        /* 1 — OK не дочекалися */
	uint8_t decided = 0u;

	at_reply_len = 0u;
	at_reply[0] = '\0';

	if (HAL_UART_Transmit(&huart4, (uint8_t *) command,
			(uint16_t) strlen(command), 200u) != HAL_OK) {
		at_log(command, 0u);
		return 1u;
	}

	start = HAL_GetTick();
	while (!decided && ((uint32_t) (HAL_GetTick() - start) < timeout_ms)) {
		if (HAL_UART_Receive(&huart4, &ch, 1u, 10u) != HAL_OK) {
			continue;
		}
		if (at_reply_len < (sizeof(at_reply) - 1u)) {
			/* CR і LF у журналі показуємо точкою, щоб рядок не розривався. */
			at_reply[at_reply_len] = ((ch == '\r') || (ch == '\n')) ? '.' : (char) ch;
			at_reply_len++;
		}
		if (ch == '\r') {
			continue;
		}
		if (ch == '\n') {
			line[used] = '\0';
			if (strcmp(line, "OK") == 0) {
				result = 0u;
				decided = 1u;
			} else if (strncmp(line, "ERROR", 5u) == 0) {
				result = 1u;
				decided = 1u;
			} else {
				used = 0u;      /* незапитана подія — пропускаємо */
			}
		} else if (used < (sizeof(line) - 1u)) {
			line[used] = (char) ch;
			used++;
		} else {
			used = 0u;
		}
	}
	at_reply[at_reply_len] = '\0';
	at_log(command, decided);
	return result;
}

/* Приведення WRLS_WKUP_B (PG6) до визначеного стану.
 *
 * CubeMX конфігурує цю ногу виходом і кладе в нуль (MX_GPIO_Init), після чого
 * її більше ніхто не торкається. Приклад ST BLE_AT_Client не конфігурує її
 * взагалі — там вона лишається входом. Вихід у нулі не збігається ні з тим, ні
 * з іншим, тому стан задаємо тут явно.
 *
 * ПЕРЕВІРЕНО НА ПЛАТІ: з HAR_BLE_DRIVE_WAKE_PIN = 1 модуль відповідає на
 * просту команду AT. Тобто це активно-високий дозвіл, як у WRLS_WKUP_W
 * модуля Wi-Fi.
 *
 * Робимо це в har_ble.c, а не в main.c, щоб налаштування переживало
 * перегенерацію проєкту з .ioc. */
static void wake_module(void)
{
#if HAR_BLE_DRIVE_WAKE_PIN
	/* Короткий нуль, потім одиниця: модуль стартує з чистого стану навіть
	   після програмного перезапуску головного МК без знеструмлення. */
	HAL_GPIO_WritePin(WRLS_WKUP_B_GPIO_Port, WRLS_WKUP_B_Pin, GPIO_PIN_RESET);
	HAL_Delay(50u);
	HAL_GPIO_WritePin(WRLS_WKUP_B_GPIO_Port, WRLS_WKUP_B_Pin, GPIO_PIN_SET);
#else
	GPIO_InitTypeDef init = { 0 };

	init.Pin = WRLS_WKUP_B_Pin;
	init.Mode = GPIO_MODE_INPUT;
	init.Pull = GPIO_NOPULL;
	HAL_GPIO_Init(WRLS_WKUP_B_GPIO_Port, &init);
#endif
}

#if HAR_BLE_PROBE
/* Одноразове зондування модуля: що він узагалі вміє. UART4 заведений на
   модуль, з ноутбука до нього не дотягнутися, тому єдиний спосіб дізнатися —
   спитати з прошивки й надрукувати відповіді в USB.

   Набір підібраний так, щоб розділити три різні причини відмови:
     BLE_PUB_ADDR? — читання адреси. Без живого стека BLE не відповість.
     BLE_NAME?     — чи команда взагалі існує в цій збірці сервера.
     BLE_SVC=1     — рівно те, що робить робочий приклад ST: вибір наперед
                     визначеного сервісу, без створення власного.
     BLE_RST=1     — спроба перезапустити підсистему. */
static void probe_module(void)
{
	static const char *const list[] = {
		/* Контроль 1: відома робоча команда. Очікуємо OK. */
		"AT\r\n",
		/* Контроль 2: свідомо вигадана команда. Якщо відповідь така сама, як
		   на AT+BLE_*, то сервер вважає BLE_* невідомими — тобто на модулі
		   інший набір команд, а не мертвий стек. Це розрізняє дві причини. */
		"AT+ZZZZ?\r\n",
		/* Чи знає модуль про себе: версія, довідка, адреса. Різні збірки
		   відповідають на щось одне з цього. */
		"AT+VERSION?\r\n",
		"AT+VERS?\r\n",
		"AT+GMR\r\n",
		"ATI\r\n",
		"AT+HELP?\r\n",
		/* Діалект HM-10/HC-05: короткі імена без префікса BLE_. */
		"AT+NAME?\r\n",
		"AT+ADDR?\r\n",
		"AT+MAC?\r\n",
		"AT+ROLE?\r\n",
		/* Діалект ST: те, що вже впало, для порівняння в одному журналі. */
		"AT+BLE_PUB_ADDR?\r\n",
		"AT+BLE_SVC=1\r\n",
	};

	printf("# --- ble probe ---\r\n");
	for (unsigned i = 0u; i < (sizeof(list) / sizeof(list[0])); i++) {
		(void) at_command(list[i], 1500u);
		HAL_Delay(200u);
	}
	printf("# --- probe end ---\r\n");
	HAL_Delay(500u);
}
#endif

uint8_t har_ble_init(void)
{
	ready = 0u;
	fail_streak = 0u;
	last_ok = 0u;
	soft_fail = 0u;
	hold_until = 0u;

	wake_module();
	HAL_Delay(2000u);

	/* Обов'язковий крок: якщо модуль не відповідає на AT, говорити з ним
	   нічим і далі йти немає сенсу. */
	if (at_command("AT\r\n", 1000u)) {
		return 1u;
	}

#if HAR_BLE_PROBE
	probe_module();
#endif

	/* Назва пристрою — косметика. Сайт шукає плату за UUID сервісу
	   (requestDevice з acceptAllDevices), а не за назвою, тому відмова тут не
	   має валити всю ініціалізацію. Офіційний приклад ST цієї команди не
	   надсилає взагалі, тож не всі збірки BLE_AT_Server її мають. */
	if (at_command("AT+BLE_NAME=Spokiy\r\n", 1000u)) {
		soft_fail |= HAR_BLE_SOFT_NAME;
	}
	HAL_Delay(150u);

	/* Так само необов'язковий: приклад ST не викликає BLE_INIT, а одразу
	   вибирає сервіс. */
	if (at_command("AT+BLE_INIT=1\r\n", 2000u)) {
		soft_fail |= HAR_BLE_SOFT_INIT;
	}
	HAL_Delay(150u);

	/* Далі — обов'язкове: без сервісу, характеристики й реклами передавати
	   нічого й нікуди. */
	if (at_command("AT+BLE_SVC=3,2,0xaabb,10\r\n", 2000u)) {
		return 4u;
	}
	HAL_Delay(150u);
	if (at_command("AT+BLE_CHAR_ADD=3,1,2,0x3344,20,0x10,0,0\r\n", 2000u)) {
		return 5u;
	}
	HAL_Delay(150u);
	if (at_command("AT+BLE_ADV=1\r\n", 2000u)) {
		return 6u;
	}

	readv_at = HAL_GetTick();
	ready = 1u;
	return 0u;
}

uint8_t har_ble_ready(void)
{
	return ready;
}

uint8_t har_ble_soft_fail(void)
{
	return soft_fail;
}

uint8_t har_ble_delivering(void)
{
	return (uint8_t) (ready && last_ok && (hold_until == 0u));
}

/* Одне сповіщення. Для одного байта сервер чекає десяткове значення, а не
 * 0x-рядок: офіційний клієнт ST розгалужується на val_tab_len <= 1 саме так.
 * Найдовша команда: 21 + 2 + 2*18 + 2 + 1 = 62 байти, буфер 80. */
static uint8_t send_chunk(const char *data, uint16_t count)
{
	static const char hex[] = "0123456789abcdef";
	char command[80];
	uint16_t pos = 21u;

	memcpy(command, "AT+BLE_NOTIF_VAL=3,1,", 21u);
	if (count == 1u) {
		pos += (uint16_t) sprintf(&command[pos], "%u",
				(unsigned) (uint8_t) data[0]);
	} else {
		command[pos++] = '0';
		command[pos++] = 'x';
		for (uint16_t i = 0u; i < count; i++) {
			const uint8_t b = (uint8_t) data[i];

			command[pos++] = hex[b >> 4];
			command[pos++] = hex[b & 15u];
		}
	}
	command[pos++] = '\r';
	command[pos++] = '\n';
	command[pos] = '\0';
	return at_command(command, 500u);
}

uint8_t har_ble_send(const char *data, uint16_t len)
{
	uint16_t offset = 0u;

	if (!ready || (data == NULL) || (len == 0u)) {
		return 1u;
	}

	/* Пауза після серії невдач: мовчазний модуль не має з'їдати період вікна. */
	if (hold_until != 0u) {
		if ((int32_t) (HAL_GetTick() - hold_until) < 0) {
			return 1u;
		}
		hold_until = 0u;
	}

	/* Поновлення реклами: без цього плата зникає з ефіру після першого ж
	   відключення клієнта. Робимо це перед відправкою, а не після, щоб
	   команда не вклинювалася між частинами одного повідомлення. */
	if ((uint32_t) (HAL_GetTick() - readv_at) >= HAR_BLE_READV_MS) {
		readv_at = HAL_GetTick();
		(void) at_command("AT+BLE_ADV=1\r\n", 500u);
	}

	while (offset < len) {
		uint16_t count = (uint16_t) (len - offset);

		if (count > HAR_BLE_CHUNK_SIZE) {
			count = HAR_BLE_CHUNK_SIZE;
			/* Хвіст в один байт кодується інакше, ніж решта, тому простіше
			   його не створювати: 18 + 1 перетворюємо на 17 + 2. */
			if ((uint16_t) (len - offset - count) == 1u) {
				count--;
			}
		}
		if (send_chunk(&data[offset], count)) {
			/* Поки браузер не підписався на характеристику, ERROR — очікувана
			   відповідь. Канал не гасимо назавжди: інакше BLE помер би ще до
			   того, як сайт встигне підключитися. Але й не впираємося: після
			   HAR_BLE_FAIL_LIMIT невдач беремо паузу й перезапускаємо рекламу,
			   бо модуль міг перезавантажитися. */
			last_ok = 0u;
			if (++fail_streak >= HAR_BLE_FAIL_LIMIT) {
				fail_streak = 0u;
				hold_until = HAL_GetTick() + HAR_BLE_BACKOFF_MS;
				if (hold_until == 0u) {
					hold_until = 1u;        /* 0 означає «паузи нема» */
				}
				(void) at_command("AT+BLE_ADV=1\r\n", 1000u);
			}
			return 1u;
		}
		/* The server processes updates asynchronously. Avoid replacing a
		 * pending update before the radio stack has consumed it. Пауза
		 * коротка навмисно: кожна мілісекунда тут — це відліки, яких не
		 * прочитає головний цикл. Стислий рядок уміщається в одне
		 * сповіщення, тож зазвичай ця пауза взагалі не настає. */
		HAL_Delay(HAR_BLE_CHUNK_GAP_MS);
		offset = (uint16_t) (offset + count);
	}
	fail_streak = 0u;
	last_ok = 1u;
	return 0u;
}
#else
uint8_t har_ble_init(void) { return 0u; }
uint8_t har_ble_ready(void) { return 0u; }
uint8_t har_ble_soft_fail(void) { return 0u; }
uint8_t har_ble_delivering(void) { return 0u; }
uint8_t har_ble_send(const char *data, uint16_t len) { (void) data; (void) len; return 0u; }
#endif
