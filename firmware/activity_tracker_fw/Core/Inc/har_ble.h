/* STM32WB BLE_AT_Server custom prediction service over UART4. */
#ifndef HAR_BLE_H
#define HAR_BLE_H
#include <stdint.h>

/* Set to 0 to use UART4 for another purpose. USB diagnostics remain enabled. */
#define HAR_BLE_ENABLED 1
#define HAR_BLE_CHUNK_SIZE 18u

/* 0 is success; nonzero identifies the failing initialization step. */
uint8_t har_ble_init(void);
/* Send a newline-terminated prediction using <=18-byte BLE notifications. */
uint8_t har_ble_send(const char *data, uint16_t len);
#endif
