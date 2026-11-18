# Bluetooth prediction setup

The main STM32U585 firmware keeps its ST-Link USB output and sends each model prediction to the STM32WB5MMG over UART4 at 9600 baud using ST's BLE_AT_Server commands. `HAR_BLE_ENABLED` in `activity_tracker_fw/Core/Inc/har_ble.h` controls this; it is enabled by default. No `stm32wb_at` component is required by this implementation. Do not select `HAR_OUT_BLE`; keep `HAR_OUT_STLINK`. UART4 cannot simultaneously be used by an external module.

The custom service UUID is `0000aabb-cc7a-482a-984a-7f2ed5b3e58f`; its notification characteristic is `00003344-8e22-4541-9d4c-21edae82ed19`. The advertised name is configured as `Spokiy`. Predictions are UTF-8 `# pred t=... class=... p=...\r\n` lines, split into notifications no larger than 18 bytes. These UUIDs are based on ST BLE_AT_Server custom UUID bases, not the predefined P2P button service.

## Board preparation

1. Build and flash `activity_tracker_fw` to the STM32U585 using STM32CubeIDE. Then fully power-cycle the board so both processors start cleanly.
2. Open the ST-Link virtual COM port at 115200 baud. Look for `# ble=ok step=0`. A `# ble=fail step=N` line identifies the first command that did not receive OK: 1 AT, 2 name, 3 initialization, 4 service, 5 characteristic, 6 advertising. `ok` means AT commands were acknowledged; it does not prove that the wireless stack completed each asynchronous operation.
3. With ST BLE Toolbox, scan for `Spokiy`, connect, discover the UUIDs above, and enable notifications. Wait for an inference window. A prediction may span several notifications; concatenate bytes until the newline. Disconnect the phone before connecting the website.
4. Run the app and connect in Chrome or Edge on a Bluetooth-capable computer. See `spokiy_app/README.md`.

If step 1 fails or `Spokiy` is absent, check that the module's existing firmware is BLE_AT_Server and its wireless stack is compatible. Do not assume the module is blank or blindly replace FUS or wireless stack firmware. ST's [B-U585I-IOT02A BLE_AT_Client reference](https://github.com/STMicroelectronics/STM32CubeU5/tree/main/Projects/B-U585I-IOT02A/Applications/BLE/BLE_AT_Client) documents its required stack/server, external ST-LINK and CN5 flashing setup; follow the release notes matching the installed STM32CubeWB version and inspect existing versions first.

The module firmware and board have not been tested here. AT operations are synchronous and BLE transmissions may cause missed IMU samples; inspect the firmware's `# rate` and `missed` diagnostics on USB. The server schedules GATT operations asynchronously; command acknowledgements do not establish radio delivery. Disconnect/reconnect, long-running operation and inference timing require board tests. For iPhone, ST BLE Toolbox can inspect notifications, but the website's Web Bluetooth flow needs a supported desktop browser.
