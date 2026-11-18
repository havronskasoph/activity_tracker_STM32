/* BLE_AT_Server custom service. The board's STM32WB module must already run
 * ST's BLE_AT_Server and a compatible wireless stack. Communication uses the
 * same UART4/9600/8N1 connection as ST's B-U585I-IOT02A example.
 *
 * Custom service UUID:        0000aabb-cc7a-482a-984a-7f2ed5b3e58f
 * Notification UUID:         00003344-8e22-4541-9d4c-21edae82ed19
 */
#include "har_ble.h"
#include "main.h"
#include <stdio.h>
#include <string.h>

#if HAR_BLE_ENABLED
extern UART_HandleTypeDef huart4;
static uint8_t ready;

/* Wait for the command's OK or ERROR. Unsolicited events are ignored.
 * A bounded timeout ensures a missing radio never hangs the inference loop. */
static uint8_t at_command(const char *command, uint32_t timeout_ms)
{
    char line[96];
    uint16_t used = 0;
    uint32_t start = HAL_GetTick();
    uint8_t ch;
    if (HAL_UART_Transmit(&huart4, (uint8_t *)command,
                          (uint16_t)strlen(command), 200u) != HAL_OK) return 1u;
    while ((uint32_t)(HAL_GetTick() - start) < timeout_ms) {
        if (HAL_UART_Receive(&huart4, &ch, 1u, 10u) != HAL_OK) continue;
        if (ch == '\r') continue;
        if (ch == '\n') {
            line[used] = '\0';
            if (strcmp(line, "OK") == 0) return 0u;
            if (strncmp(line, "ERROR", 5u) == 0) return 1u;
            used = 0;
        } else if (used < sizeof(line) - 1u) {
            line[used++] = (char)ch;
        } else {
            used = 0;
        }
    }
    return 1u;
}

uint8_t har_ble_init(void)
{
    ready = 0u;
    HAL_Delay(2000u);
    if (at_command("AT\r\n", 1000u)) return 1u;
    if (at_command("AT+BLE_NAME=Spokiy\r\n", 1000u)) return 2u;
    if (at_command("AT+BLE_INIT=1\r\n", 2000u)) return 3u;
    HAL_Delay(150u);
    if (at_command("AT+BLE_SVC=3,2,0xaabb,10\r\n", 2000u)) return 4u;
    HAL_Delay(150u);
    if (at_command("AT+BLE_CHAR_ADD=3,1,2,0x3344,20,0x10,0,0\r\n", 2000u)) return 5u;
    HAL_Delay(150u);
    if (at_command("AT+BLE_ADV=1\r\n", 2000u)) return 6u;
    ready = 1u;
    return 0u;
}

uint8_t har_ble_send(const char *data, uint16_t len)
{
    static const char hex[] = "0123456789abcdef";
    char command[80];
    uint16_t offset = 0;
    if (!ready || !data || !len) return 1u;
    while (offset < len) {
        uint16_t count = (uint16_t)(len - offset);
        if (count > HAR_BLE_CHUNK_SIZE) count = HAR_BLE_CHUNK_SIZE;
        memcpy(command, "AT+BLE_NOTIF_VAL=3,1,0x", 23u);
        uint16_t pos = 23u;
        for (uint16_t i = 0; i < count; i++) {
            uint8_t b = (uint8_t)data[offset + i];
            command[pos++] = hex[b >> 4];
            command[pos++] = hex[b & 15u];
        }
        command[pos++] = '\r'; command[pos++] = '\n'; command[pos] = '\0';
        if (at_command(command, 500u)) { ready = 0u; return 1u; }
        /* The server processes updates asynchronously. Avoid replacing a
         * pending update before the radio stack has consumed it. */
        HAL_Delay(40u);
        offset = (uint16_t)(offset + count);
    }
    return 0u;
}
#else
uint8_t har_ble_init(void) { return 0u; }
uint8_t har_ble_send(const char *data, uint16_t len) { (void)data; (void)len; return 0u; }
#endif
