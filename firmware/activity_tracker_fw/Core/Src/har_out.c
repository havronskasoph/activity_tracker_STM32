/* Реалізація шару виводу. Див. har_out.h. */
#include "har_out.h"

#include <string.h>

#include "main.h"
#include "har_ble.h"

extern UART_HandleTypeDef huart1;
extern UART_HandleTypeDef huart4;

#if HAR_OUT_PORT == HAR_OUT_BLE

/* BLE шле сповіщеннями, тому вивід накопичується до кінця рядка. */
static char line_buf[HAR_BLE_MTU];
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
	if (data == NULL) {
		return;
	}
	for (uint16_t i = 0u; i < len; i++) {
		const char ch = data[i];

		if (ch == '\r') {
			continue;                 /* CR не несе змісту для BLE */
		}
		if (ch == '\n') {
			flush_line();
			continue;
		}
		if (line_len >= sizeof(line_buf)) {
			flush_line();             /* рядок довший за сповіщення — ріжемо */
		}
		line_buf[line_len++] = ch;
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
	return "BLE (STM32WB5MMG, UART4 9600)";
#elif HAR_OUT_PORT == HAR_OUT_UART4
	return "UART4 (PC10/PC11, зовнішній модуль)";
#else
	return "USART1 (ST-Link VCP)";
#endif
}
