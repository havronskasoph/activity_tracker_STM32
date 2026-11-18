import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class BLETransportTest(unittest.TestCase):
    def test_commands_chunks_and_timeout(self):
        gcc = shutil.which('gcc')
        if not gcc:
            self.skipTest('gcc is required for the host HAL simulation')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'main.h').write_text('''#include <stdint.h>
typedef struct { int unused; } UART_HandleTypeDef;
#define HAL_OK 0
int HAL_UART_Transmit(UART_HandleTypeDef*, uint8_t*, uint16_t, uint32_t);
int HAL_UART_Receive(UART_HandleTypeDef*, uint8_t*, uint16_t, uint32_t);
uint32_t HAL_GetTick(void);
void HAL_Delay(uint32_t);
''')
            (tmp / 'test.c').write_text(r'''#include "main.h"
#include "har_ble.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
UART_HandleTypeDef huart4;
static unsigned tick, cmd_count, rx_pos;
static int reply = 1;
static char commands[10][80];
uint32_t HAL_GetTick(void) { return tick++; }
void HAL_Delay(uint32_t n) { tick += n; }
int HAL_UART_Transmit(UART_HandleTypeDef *p, uint8_t *data, uint16_t n, uint32_t timeout) {
  (void)p; (void)timeout; assert(cmd_count < 10 && n < 80);
  memcpy(commands[cmd_count], data, n); commands[cmd_count][n] = 0; cmd_count++; rx_pos = 0; return HAL_OK;
}
int HAL_UART_Receive(UART_HandleTypeDef *p, uint8_t *data, uint16_t n, uint32_t timeout) {
  (void)p; (void)n; (void)timeout;
  if (!reply) { tick += 10; return 1; }
  const char *response = "\r\n+BLE_EVT_CONN:1\r\nOK\r\n";
  if (rx_pos >= strlen(response)) return 1;
  *data = response[rx_pos++]; return HAL_OK;
}
int main(void) {
  assert(har_ble_init() == 0); assert(cmd_count == 6);
  assert(strcmp(commands[3], "AT+BLE_SVC=3,2,0xaabb,10\r\n") == 0);
  assert(strcmp(commands[4], "AT+BLE_CHAR_ADD=3,1,2,0x3344,20,0x10,0,0\r\n") == 0);
  const char *data = "# pred t=7 class=Lying p=0.969\r\n";
  assert(har_ble_send(data, (uint16_t)strlen(data)) == 0); assert(cmd_count == 8);
  assert(strcmp(commands[6], "AT+BLE_NOTIF_VAL=3,1,0x23207072656420743d3720636c6173733d4c\r\n") == 0);
  assert(strcmp(commands[7], "AT+BLE_NOTIF_VAL=3,1,0x79696e6720703d302e3936390d0a\r\n") == 0);
  reply = 0; assert(har_ble_init() == 1); assert(har_ble_send(data, 1) != 0);
  return 0;
}
''')
            exe = tmp / 'ble_test.exe'
            subprocess.run([gcc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(tmp), '-I', str(ROOT / 'firmware/activity_tracker_fw/Core/Inc'), str(ROOT / 'firmware/activity_tracker_fw/Core/Src/har_ble.c'), str(tmp / 'test.c'), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

if __name__ == '__main__':
    unittest.main()
