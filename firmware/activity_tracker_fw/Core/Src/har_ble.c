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
static uint8_t  readv_due;      /* сервер повідомив про відключення */
static uint8_t  peer_connected; /* за даними подій клієнт підключений */
static uint32_t readv_at;       /* тік останнього поновлення реклами */
static uint32_t silent_since;   /* відколи модуль не сказав жодного байта */
static uint8_t  revive_tries;   /* скільки разів уже пробували оживити */
static uint32_t revive_at;      /* тік останньої спроби оживлення */

/* Останній обмін із модулем — для журналу. Пишемо сюди під час команди, а
   друкуємо вже після неї: printf у USART1 блокує на ~87 мкс на символ, і
   якби ми друкували всередині циклу прийому, то губили б байти відповіді,
   бо на UART4 немає ні перивань, ні DMA. */
static char at_reply[192];
static uint16_t at_reply_len;

/* ── Приймання UART4 на перериваннях ──────────────────────────────────
 *
 * Спершу приймання було опитуванням: HAL_UART_Receive лише тоді, коли ми
 * чекаємо відповідь на команду. Це не працює, і ось чому.
 *
 * Модуль шле події асинхронно — зокрема про підключення й відключення
 * клієнта. Між командами ми не читаємо, а в приймачі вміщається один байт,
 * тому подія втрачається: у журналі від неї лишався самий обрізок "<".
 * Через це прошивка не могла дізнатися, що клієнт відійшов, і поновити
 * рекламу — плату було видно рівно один раз за ввімкнення.
 *
 * Гірше: втрачені байти виставляють помилку переповнення (ORE), після якої
 * приймач лишається непрацездатним, поки прапорець не скинути. Саме так і
 * виглядало «зависання модуля» через 19 хвилин: мовчав не модуль, а наш
 * власний приймач.
 *
 * Тому власний кільцевий буфер, наповнення з переривання, і обов'язкове
 * очищення прапорців помилок із переозброєнням.
 */
#define HAR_BLE_RX_RING  256u

static volatile uint8_t rx_ring[HAR_BLE_RX_RING];
static volatile uint16_t rx_head;
static volatile uint16_t rx_tail;
static uint8_t rx_byte;

static void rx_arm(void)
{
	(void) HAL_UART_Receive_IT(&huart4, &rx_byte, 1u);
}

void UART4_IRQHandler(void)
{
	HAL_UART_IRQHandler(&huart4);
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
	if (huart->Instance == UART4) {
		const uint16_t next = (uint16_t) ((rx_head + 1u) % HAR_BLE_RX_RING);

		if (next != rx_tail) {          /* переповнення буфера — байт гине */
			rx_ring[rx_head] = rx_byte;
			rx_head = next;
		}
		rx_arm();
	}
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
	if (huart->Instance == UART4) {
		__HAL_UART_CLEAR_OREFLAG(huart);
		__HAL_UART_CLEAR_NEFLAG(huart);
		__HAL_UART_CLEAR_FEFLAG(huart);
		__HAL_UART_CLEAR_PEFLAG(huart);
		huart->ErrorCode = HAL_UART_ERROR_NONE;
		rx_arm();
	}
}

/* Наступний байт із буфера, або -1, якщо порожньо. */
static int rx_get(void)
{
	int c;

	if (rx_head == rx_tail) {
		return -1;
	}
	c = (int) rx_ring[rx_tail];
	rx_tail = (uint16_t) ((rx_tail + 1u) % HAR_BLE_RX_RING);
	return c;
}

static void rx_start(void)
{
	rx_head = 0u;
	rx_tail = 0u;
	HAL_NVIC_SetPriority(UART4_IRQn, 6, 0);
	HAL_NVIC_EnableIRQ(UART4_IRQn);
	rx_arm();
}

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
/* Зібраний рядок від модуля. Повертає 1, якщо це була остаточна відповідь
   на команду (OK або ERROR), і кладе результат у *result. */
static uint8_t take_line(char *line, uint8_t *result)
{
	const char *t = line;

	/* Обрізки загублених подій лишають на початку "<". Прибираємо, інакше
	   "<OK" не розпізнається і команда даремно чекає до таймауту. */
	while (*t == '<') {
		t++;
	}
	if (*t == '\0') {
		return 0u;
	}
	if (strcmp(t, "OK") == 0) {
		*result = 0u;
		return 1u;
	}
	if (strncmp(t, "ERROR", 5u) == 0) {
		*result = 1u;
		return 1u;
	}

	/* Подія про з'єднання. Сервер шле її як "BLE_EVT_CONN=<status>"; у
	   прикладі ST розділювачем буває і ':', тому приймаємо обидва. status 0
	   означає, що клієнт відійшов, а разом із ним спинилася й реклама —
	   саме тоді її треба поновити, і тільки тоді. */
	if (strncmp(t, HAR_BLE_EVT_CONN, sizeof(HAR_BLE_EVT_CONN) - 1u) == 0) {
		const char *v = t + (sizeof(HAR_BLE_EVT_CONN) - 1u);

		if ((*v == '=') || (*v == ':')) {
			peer_connected = (uint8_t) (v[1] != '0');
			readv_due = (uint8_t) (v[1] == '0');
			readv_at = HAL_GetTick();
		}
	}
	return 0u;
}

static uint8_t at_command(const char *command, uint32_t timeout_ms)
{
	char line[96];
	uint16_t used = 0u;
	uint32_t start;
	int ch;
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
		ch = rx_get();
		if (ch < 0) {
			continue;
		}
		if (at_reply_len < (sizeof(at_reply) - 1u)) {
			/* CR і LF у журналі показуємо точкою, щоб рядок не розривався. */
			at_reply[at_reply_len] =
					((ch == '\r') || (ch == '\n')) ? '.' : (char) ch;
			at_reply_len++;
		}
		if (ch == '\r') {
			continue;
		}
		if (ch == '\n') {
			line[used] = '\0';
			used = 0u;
			decided = take_line(line, &result);
		} else if (used < (sizeof(line) - 1u)) {
			line[used] = (char) ch;
			used++;
		} else {
			used = 0u;
		}
	}
	at_reply[at_reply_len] = '\0';

	/* Відстеження тиші. Розрізняємо два стани: модуль відповів щось (хай
	   навіть ERROR) — він живий; модуль не сказав жодного байта — він завис.
	   Саме другий стан лікується оживленням, а не повторами команд. */
	if (at_reply_len > 0u) {
		silent_since = 0u;
	} else if (silent_since == 0u) {
		silent_since = HAL_GetTick();
		if (silent_since == 0u) {
			silent_since = 1u;      /* 0 означає «модуль озивається» */
		}
	}

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
static void wake_module(uint32_t low_ms)
{
#if HAR_BLE_DRIVE_WAKE_PIN
	/* Нуль, потім одиниця: модуль стартує з чистого стану навіть після
	   програмного перезапуску головного МК без знеструмлення. Довжину нуля
	   задає виклик: при звичайному старті досить короткого, при спробі
	   оживити зависле модуля потрібен довгий. */
	HAL_GPIO_WritePin(WRLS_WKUP_B_GPIO_Port, WRLS_WKUP_B_Pin, GPIO_PIN_RESET);
	HAL_Delay(low_ms);
	HAL_GPIO_WritePin(WRLS_WKUP_B_GPIO_Port, WRLS_WKUP_B_Pin, GPIO_PIN_SET);
#else
	(void) low_ms;
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
		/* Чи живий стек BLE: читання власної адреси нічого не налаштовує,
		   але без працюючого стека не виконується. */
		"AT+BLE_PUB_ADDR?\r\n",
		/* Чи вважає сервер, що реклама ввімкнена. */
		"AT+BLE_ADV?\r\n",
		/* Чи зареєстрований наш сервіс. */
		"AT+BLE_SVC?\r\n",
		/* Контроль: відома робоча команда. Очікуємо OK. */
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

/* Повний підйом каналу. low_ms — довжина нуля на лінії дозволу модуля:
   коротка при звичайному старті, довга при спробі оживити зависле. */
static uint8_t bring_up(uint32_t low_ms)
{
	ready = 0u;
	fail_streak = 0u;
	last_ok = 0u;
	soft_fail = 0u;
	hold_until = 0u;
	readv_due = 0u;

	wake_module(low_ms);
	HAL_Delay(2000u);

	/* Обов'язковий крок: якщо модуль не відповідає на AT, говорити з ним
	   нічим і далі йти немає сенсу. */
	if (at_command("AT\r\n", 1000u)) {
		return 1u;
	}

	/* Скидання підсистеми BLE перед будь-яким налаштуванням.

	   ЗАМІРЯНО НА ПЛАТІ: модуль може лишитися у «фантомному» з'єднанні —
	   клієнт давно відійшов, а сервер і далі вважає його підключеним. У
	   цьому стані він бадьоро відповідає OK на все, на AT+BLE_ADV? звітує 1
	   і навіть віддає свою адресу через AT+BLE_PUB_ADDR?, але в ефір не йде,
	   бо підключений пристрій реклами не веде. Знайти його стає неможливо
	   ні з телефона, ні з ноутбука.

	   Скидання рве будь-яке таке з'єднання і повертає радіо в чистий стан.
	   Відмова тут не критична: на свіжому модулі скидати нічого. */
#if HAR_BLE_RESET_ON_BOOT
	if (at_command("AT+BLE_RST=1\r\n", 2000u)) {
		soft_fail |= HAR_BLE_SOFT_RST;
	}
	HAL_Delay(500u);
#endif

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

	ready = 1u;
	return 0u;
}

uint8_t har_ble_init(void)
{
	uint8_t step;

	silent_since = 0u;
	revive_tries = 0u;
	revive_at = 0u;
	peer_connected = 0u;
	readv_at = HAL_GetTick();
	rx_start();

	step = bring_up(50u);

	/* Якщо модуль не озвався на просту AT, він міг лишитися зависим із
	   минулого разу — перезапуск головного МК його не чіпає. Пробуємо ще раз
	   із довгим нулем на лінії дозволу. Ці 5 секунд витрачаються лише тоді,
	   коли без них усе одно нічого не працювало б. */
	if (step == 1u) {
		step = bring_up(HAR_BLE_REVIVE_LOW_MS);
	}
	return step;
}

/* Спроба оживити зависле модуля. Запускається лише тоді, коли він мовчить
   (не ERROR, а жодного байта) довше за HAR_BLE_REVIVE_MS.

   ЗАМІРЯНО НА ПЛАТІ: модуль здатен зависнути намертво — тоді ні програмне
   скидання головного МК, ні короткий імпульс на лінії дозволу його не
   повертають. Тому тут довгий нуль. Спроб небагато: кожна блокує головний
   цикл на кілька секунд, і якщо модуль не відгукнувся після
   HAR_BLE_REVIVE_TRIES, далі смикати його марно — краще віддати весь час
   інференсу, а про стан сказати червоним світлодіодом. */
static void try_revive(void)
{
	revive_at = HAL_GetTick();
	revive_tries++;

	if (bring_up(HAR_BLE_REVIVE_LOW_MS) == 0u) {
		silent_since = 0u;
		revive_tries = 0u;
	}
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

	if ((data == NULL) || (len == 0u)) {
		return 1u;
	}

	if (!ready) {
		/* Канал лежить. Якщо модуль мовчить і спроби ще не вичерпані —
		   зрідка пробуємо його оживити. Поки спроб немає, ця гілка не
		   коштує нічого, і весь час іде інференсу. */
		if ((revive_tries < HAR_BLE_REVIVE_TRIES)
				&& ((uint32_t) (HAL_GetTick() - revive_at) >= HAR_BLE_REVIVE_MS)) {
			try_revive();
		}
		return 1u;
	}

	/* Пауза після серії невдач: мовчазний модуль не має з'їдати період вікна. */
	if (hold_until != 0u) {
		if ((int32_t) (HAL_GetTick() - hold_until) < 0) {
			return 1u;
		}
		hold_until = 0u;

		/* Пауза вийшла, а модуль так і не озвався жодним байтом — це не
		   «зайнятий», це завис. Припиняємо слати в порожнечу: ready = 0
		   повертає повну частоту вибірки, а оживленням займеться гілка
		   вище, за розкладом. */
		if ((silent_since != 0u)
				&& ((uint32_t) (HAL_GetTick() - silent_since) >= HAR_BLE_REVIVE_MS)) {
			ready = 0u;
			revive_at = HAL_GetTick();
			return 1u;
		}
	}

	/* Поновлення реклами — коли сервер сам сказав, що клієнт відключився.
	   Сліпе повторення кожні 20 с свого часу доконало модуль за 19 хвилин,
	   тому за розкладом тут лише рідкісна підстраховка на випадок, якщо
	   подію про відключення все-таки проґавили. */
	if (!readv_due && !peer_connected
			&& ((uint32_t) (HAL_GetTick() - readv_at) >= HAR_BLE_READV_SAFETY_MS)) {
		readv_due = 1u;
	}
	if (readv_due) {
		readv_due = 0u;
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
