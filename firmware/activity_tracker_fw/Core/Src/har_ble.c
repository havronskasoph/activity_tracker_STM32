/* Передача по BLE через STM32WB5MMG. Див. har_ble.h.
 *
 * Увесь вміст активний лише коли HAR_OUT_PORT == HAR_OUT_BLE. Інакше файл
 * компілюється в порожнечу, щоб проєкт збирався без компонента stm32wb_at.
 */
#include "har_ble.h"

#if HAR_OUT_PORT == HAR_OUT_BLE

#include <string.h>

#include "main.h"
#include "stm32wb_at.h"
#include "stm32wb_at_ble.h"
#include "stm32wb_at_client.h"

extern UART_HandleTypeDef huart4;

/* Буфер, у який драйвер складає відповіді модуля. 64 байти — як у прикладі ST. */
static uint8_t at_buffer[64];

/* Один байт, який приймається по перериванню. */
static uint8_t rx_byte;

static volatile uint8_t connected;

uint8_t har_ble_connected(void)
{
	return connected;
}

uint8_t har_ble_init(void)
{
	/* Переривання UART4 вмикаємо тут, а не в згенерованому CubeMX коді:
	   так налаштування переживе перегенерацію проєкту з .ioc. */
	HAL_NVIC_SetPriority(UART4_IRQn, 6, 0);
	HAL_NVIC_EnableIRQ(UART4_IRQn);

	/* Модулю потрібен час після подачі живлення, перш ніж він відповідатиме. */
	HAL_Delay(2000);

	if (stm32wb_at_Init(&at_buffer[0], sizeof(at_buffer)) != 0u) {
		return 1u;
	}
	if (stm32wb_at_client_Init() != 0u) {
		return 2u;
	}
	/* Порожня команда AT: перевірка, що модуль узагалі відповідає. */
	if (stm32wb_at_client_Query(BLE_TEST) != 0u) {
		return 3u;
	}

	stm32wb_at_BLE_SVC_t svc;
	memset(&svc, 0, sizeof(svc));
	svc.index = HAR_BLE_SVC_INDEX;
	if (stm32wb_at_client_Set(BLE_SVC, &svc) != 0u) {
		return 4u;
	}
	return 0u;
}

uint8_t har_ble_send(const char *data, uint16_t len)
{
	stm32wb_at_BLE_NOTIF_VAL_t notif;

	if (data == NULL || len == 0u) {
		return 0u;
	}
	if (len > HAR_BLE_MTU) {
		len = HAR_BLE_MTU;          /* довше одне сповіщення не вміщає */
	}

	memset(&notif, 0, sizeof(notif));
	notif.svc_index = HAR_BLE_SVC_INDEX;
	notif.char_index = HAR_BLE_CHAR_INDEX;
	memcpy(notif.val_tab, data, len);
	notif.val_tab_len = (uint8_t) len;

	return stm32wb_at_client_Set(BLE_NOTIF_VAL, &notif);
}

/* ── Транспорт, якого вимагає драйвер ST ──────────────────────────────── */
/* У бібліотеці ці дві функції оголошені як __weak і повертають помилку;
   застосунок зобов'язаний дати свої. */

uint8_t stm32wb_at_ll_Transmit(uint8_t *pBuff, uint16_t Size)
{
	return (HAL_UART_Transmit(&huart4, pBuff, Size, 0xFFFFu) == HAL_OK) ? 0u : 1u;
}

void stm32wb_at_ll_Async_receive(uint8_t new_frame)
{
	(void) new_frame;
	/* Переозброюємо приймач на наступний байт. */
	(void) HAL_UART_Receive_IT(&huart4, &rx_byte, 1u);
}

/* Обробник переривання UART4. У startup-файлі він оголошений слабким, тож
   наше визначення просто заміщає заглушку — CubeMX про це знати не треба. */
void UART4_IRQHandler(void)
{
	HAL_UART_IRQHandler(&huart4);
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *UartHandle)
{
	if (UartHandle->Instance == UART4) {
		(void) stm32wb_at_Received(rx_byte);
	}
}

/* ── Події від модуля ─────────────────────────────────────────────────── */

uint8_t stm32wb_at_BLE_EVT_CONN_cb(stm32wb_at_BLE_EVT_CONN_t *param)
{
	connected = (param != NULL) ? param->status : 0u;
	return 0u;
}

uint8_t stm32wb_at_BLE_EVT_WRITE_cb(stm32wb_at_BLE_EVT_WRITE_t *param)
{
	/* Запис із телефона нам поки не потрібен, але callback має існувати:
	   драйвер викликає його при надходженні даних. */
	(void) param;
	return 0u;
}

#else  /* HAR_OUT_PORT != HAR_OUT_BLE */

uint8_t har_ble_init(void)
{
	return 0u;
}

uint8_t har_ble_send(const char *data, uint16_t len)
{
	(void) data;
	(void) len;
	return 0u;
}

uint8_t har_ble_connected(void)
{
	return 0u;
}

#endif /* HAR_OUT_PORT == HAR_OUT_BLE */
