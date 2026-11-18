/* Маршрутизація виводу.
 *
 * HAR_OUT_BLE    — потік передбачень іде в Bluetooth (STM32WB5MMG, UART4
 *                  9600). Робочий режим: плата нічого не винна USB-кабелю,
 *                  дані приймає сайт через Web Bluetooth. Якщо BLE не
 *                  піднявся, har_out сам перекидає потік у ST-Link, щоб дані
 *                  не губилися.
 * HAR_OUT_STLINK — потік у ST-Link VCP (USB, 115200). Режим для збору CSV
 *                  і для роботи без прошитого BLE-модуля.
 * HAR_OUT_UART4  — зовнішній UART-модуль на PC10/PC11; вимагає
 *                  HAR_BLE_ENABLED = 0 у har_ble.h, бо нога та сама.
 *
 * Діагностика (усе, що йде через printf) завжди виходить у ST-Link окремо від
 * цього вибору — див. har_out_diag(). Інакше рядок "# ble=fail step=N" пішов
 * би саме в той канал, якого в цей момент немає, і помилку не було б видно.
 *
 * Подробиці налаштування BLE — у firmware/BLE_SETUP.md. */
#ifndef HAR_OUT_H
#define HAR_OUT_H

#include <stdint.h>

#include "har_ble.h"

#define HAR_OUT_STLINK  0
#define HAR_OUT_UART4   1
#define HAR_OUT_BLE     2

/* Канал даних — завжди BLE, і він живе окремо: emit_pred() сам кличе
   har_ble_send() зі стислим рядком. HAR_OUT_PORT керує тільки кабельним
   виводом — повними рядками й CSV. Формати різні навмисно: по радіо на
   9600 бод кожен зайвий байт коштує втрачених відліків акселерометра. */
#ifndef HAR_OUT_PORT
#define HAR_OUT_PORT  HAR_OUT_STLINK
#endif

#if HAR_OUT_PORT == HAR_OUT_BLE && !HAR_BLE_ENABLED
#error "HAR_OUT_BLE requires HAR_BLE_ENABLED = 1 in har_ble.h"
#endif

#if HAR_OUT_PORT == HAR_OUT_UART4 && HAR_BLE_ENABLED
#error "HAR_OUT_UART4 requires HAR_BLE_ENABLED = 0 in har_ble.h (same pins)"
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Віддає len байтів у вибраний канал. Блокує до завершення передачі. */
void har_out_write(const char *data, uint16_t len);

/* Те саме, але рядком з автоматичним CRLF у кінці. */
void har_out_line(const char *text);

/* Діагностика: завжди ST-Link VCP, незалежно від HAR_OUT_PORT. */
void har_out_diag(const char *data, uint16_t len);

/* Назва активного каналу — для стартового повідомлення. */
const char *har_out_name(void);

#ifdef __cplusplus
}
#endif

#endif /* HAR_OUT_H */
