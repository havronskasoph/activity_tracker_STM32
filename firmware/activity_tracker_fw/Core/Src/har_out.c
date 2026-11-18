/* Реалізація шару виводу. Див. har_out.h. */
#include "har_out.h"

#include <string.h>

#include "main.h"
#include "har_ble.h"

extern UART_HandleTypeDef huart1;
extern UART_HandleTypeDef huart4;

/* Діагностика завжди йде в ST-Link: якщо BLE не піднявся, повідомлення саме
   про це мусить бути видно. Через цю функцію працює printf (__io_putchar). */
void har_out_diag(const char *data, uint16_t len)
{
	if (data == NULL || len == 0u) {
		return;
	}
	HAL_UART_Transmit(&huart1, (uint8_t *) data, len, HAL_MAX_DELAY);
}

#if HAR_OUT_PORT == HAR_OUT_BLE

/* BLE шле сповіщеннями, тому вивід накопичується до кінця рядка. Байти
   віддаємо як є, разом із CRLF: декодер на сайті ріже потік по '\n'. */
#define HAR_OUT_LINE_MAX  96

static char line_buf[HAR_OUT_LINE_MAX];
static uint16_t line_len;

static void flush_line(void)
{
	if (line_len > 0u) {
		(void) har_ble_send(line_buf, line_len);
		line_len = 0u;
	}
}

void har_out_write(const char *data, uint16_t len)
{
	if (data == NULL || len == 0u) {
		return;
	}
	if (!har_ble_ready()) {
		/* Каналу немає — віддаємо в кабель, щоб потік не пропав безслідно. */
		har_out_diag(data, len);
		return;
	}
	for (uint16_t i = 0u; i < len; i++) {
		if (line_len >= sizeof(line_buf)) {
			flush_line();            /* рядок довший за буфер — ріжемо */
		}
		line_buf[line_len++] = data[i];
		if (data[i] == '\n') {
			flush_line();
		}
	}
}

#else  /* канал — звичайний UART */

static UART_HandleTypeDef *har_out_port(void)
{
#if HAR_OUT_PORT == HAR_OUT_UART4
	return &huart4;
#else
	return &huart1;
#endif
}

void har_out_write(const char *data, uint16_t len)
{
	if (data == NULL || len == 0u) {
		return;
	}
	HAL_UART_Transmit(har_out_port(), (uint8_t *) data, len, HAL_MAX_DELAY);
}

#endif /* HAR_OUT_PORT == HAR_OUT_BLE */

void har_out_line(const char *text)
{
	if (text == NULL) {
		return;
	}
	har_out_write(text, (uint16_t) strlen(text));
	har_out_write("\r\n", 2u);
}

const char *har_out_name(void)
{
#if HAR_OUT_PORT == HAR_OUT_BLE
	return "BLE (Spokiy, STM32WB5MMG, UART4 9600)";
#elif HAR_OUT_PORT == HAR_OUT_UART4
	return "UART4 (PC10/PC11, зовнішній модуль)";
#else
	return "USART1 (ST-Link VCP)";
#endif
}
