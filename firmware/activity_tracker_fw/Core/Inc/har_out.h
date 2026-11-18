/* Output routing: ST-Link USB serial is the default. HAR_OUT_UART4 is for an
 * external UART module and requires HAR_BLE_ENABLED=0 in har_ble.h. BLE
 * predictions are sent separately alongside ST-Link output; see BLE_SETUP.md. */
#ifndef HAR_OUT_H
#define HAR_OUT_H

#include <stdint.h>

#define HAR_OUT_STLINK  0
#define HAR_OUT_UART4   1
#define HAR_OUT_BLE     2

#ifndef HAR_OUT_PORT
#define HAR_OUT_PORT  HAR_OUT_STLINK
#endif

#if HAR_OUT_PORT == HAR_OUT_BLE
#error "Use HAR_OUT_STLINK with HAR_BLE_ENABLED in har_ble.h for BLE predictions"
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Віддає len байтів у вибраний канал. Блокує до завершення передачі. */
void har_out_write(const char *data, uint16_t len);

/* Те саме, але рядком з автоматичним CRLF у кінці. */
void har_out_line(const char *text);

/* Назва активного каналу — для стартового повідомлення. */
const char *har_out_name(void);

#ifdef __cplusplus
}
#endif

#endif /* HAR_OUT_H */
