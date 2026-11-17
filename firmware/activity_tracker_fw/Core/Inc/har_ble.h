/* Передача результатів по Bluetooth LE через вбудований модуль STM32WB5MMG.
 *
 * На B-U585I-IOT02A два окремі бездротові модулі:
 *   EMW3080      — Wi-Fi   (лінія WRLS_WKUP_W)
 *   STM32WB5MMG  — BLE     (лінія WRLS_WKUP_B)   <- цей
 *
 * Головний мікроконтролер керує ним AT-командами по UART4 (PC10 TX, PC11 RX)
 * на швидкості 9600. Протокол реалізує компонент ST stm32wb_at; від нас він
 * вимагає лише транспорт, який і визначений у har_ble.c.
 *
 * ЩО ТРЕБА ЗРОБИТИ ОДИН РАЗ, ПЕРШ НІЖ ЦЕ ЗАПРАЦЮЄ
 * ------------------------------------------------
 * 1. Додати в проєкт компонент stm32wb_at (чотири пари .c/.h):
 *       https://github.com/STMicroelectronics/stm32-wb-at
 *    Покласти у Drivers/BSP/Components/stm32wb_at/ і додати цю теку в
 *    Project -> Properties -> C/C++ Build -> Settings -> Include paths.
 *
 * 2. Прошити сам модуль STM32WB5MMG — він порожній з заводу. Потрібні три
 *    файли з пакета STM32Cube_FW_WB:
 *       stm32wb5x_FUS_fw.bin              -> 0x080EC000
 *       stm32wb5x_BLE_Stack_full_fw.bin   -> 0x080CA000
 *       BLE_AT_Server_reference.hex       (застосунок)
 *    Прошивається через STM32CubeProgrammer, вкладка Firmware Upgrade
 *    Services, зовнішнім ST-LINK на роз'єм CN5 плати. Перемикач SW3 на час
 *    прошивання ставиться вліво, потім повертається вправо.
 *
 * 3. Увімкнути канал: у har_out.h поставити HAR_OUT_PORT = HAR_OUT_BLE.
 *
 * Поки крок 1 не зроблено, цей файл компілюється в порожнечу і нічого не
 * ламає — прошивка збирається як звичайно.
 *
 * ОБМЕЖЕННЯ
 * ---------
 * Одне сповіщення BLE вміщає 64 байти. Рядок виду
 *   "# pred t=25670 class=Lying p=0.969"
 * має близько 35 символів, тож вкладається. Довші рядки обрізаються.
 */
#ifndef HAR_BLE_H
#define HAR_BLE_H

#include <stdint.h>

#include "har_out.h"

/* Сервіс і характеристика у прошивці BLE_AT_Server: P2P, характеристика
 * сповіщень. Ті самі числа використовує офіційний приклад ST BLE_AT_Client. */
#define HAR_BLE_SVC_INDEX    1u
#define HAR_BLE_CHAR_INDEX   2u

/* Максимум, що влазить в одне сповіщення (розмір val_tab у драйвері). */
#define HAR_BLE_MTU          64u

#ifdef __cplusplus
extern "C" {
#endif

/* Піднімає зв'язок із модулем і вибирає сервіс.
 * 0 — успіх; інше число — номер кроку, на якому не вийшло:
 *   1 stm32wb_at_Init, 2 client_Init, 3 перевірка зв'язку, 4 вибір сервісу. */
uint8_t har_ble_init(void);

/* Надсилає до HAR_BLE_MTU байтів як BLE-сповіщення. 0 — успіх. */
uint8_t har_ble_send(const char *data, uint16_t len);

/* 1, якщо телефон або ноутбук підключений. */
uint8_t har_ble_connected(void);

#ifdef __cplusplus
}
#endif

#endif /* HAR_BLE_H */
