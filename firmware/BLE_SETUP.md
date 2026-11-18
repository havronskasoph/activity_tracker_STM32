# Bluetooth prediction setup

The main STM32U585 firmware sends each model prediction to the on-board
STM32WB5MMG over UART4 at 9600 baud using ST's BLE_AT_Server commands. The
radio is the normal data path: the board owes nothing to the USB cable.
No `stm32wb_at` component is required by this implementation.

Two independent channels:

| channel | carries | configured by |
|---|---|---|
| **BLE** | the prediction stream | `HAR_OUT_PORT` in `Core/Inc/har_out.h`, default `HAR_OUT_BLE` |
| **ST-Link USB, 115200** | diagnostics only (`printf`) | always on, via `har_out_diag()` |

Diagnostics stay on USB on purpose. If they shared the data channel, the line
reporting a BLE failure would be sent over the very link that failed.

If BLE does not initialize, `har_out_write()` falls back to the USB port, so
the prediction stream is still visible on a cable instead of disappearing.

## Running without a USB cable

This is the normal mode. The board needs USB **once**, to be flashed; after
that it only needs power, and all data leaves over Bluetooth.

With no cable attached, nothing reads the USB diagnostics — USART1 simply
shifts bytes out to nobody, which is harmless but invisible. The board state is
therefore also reported on the two on-board LEDs, `LED_RED` (PH6) and
`LED_GREEN` (PH7):

| LEDs | meaning |
|---|---|
| green steady | BLE is up, no prediction sent yet |
| green blinking | predictions are reaching the module, one pulse each |
| red steady | the channel is not delivering — the back-off pause is running |
| red in bursts, repeated 3× | BLE did not come up; **count the blinks** — that number is the failing step `N` from the table below |

The fault burst runs before the accelerometer interrupt is enabled, so it
costs no samples. Worst case (`N` = 6) it delays the start of classification
by about 13 seconds.

`HAR_LED_ACTIVE_HIGH` in `Core/Inc/har_led.h` assumes a logic 1 lights the LED,
which matches CubeMX's "off" initial state of 0. Set it to 0 if the board
behaves inversely.

Budget about 15 seconds from power-on before the first prediction: 2 s for the
module to boot, the AT handshake, then the first full window.

### Battery operation

The main loop sleeps (`__WFI`) whenever there is no sample to process. At
27.45 Hz the accelerometer interrupts every ~36 ms and the useful work takes
well under 1 % of that, so without sleeping the core would spin at 160 MHz
essentially all the time. The check and the sleep run with interrupts masked,
so a sample arriving in between is not lost — the IMU holds only the newest
one.

This is Sleep mode, not Stop: peripherals and SysTick keep running, so
`HAL_GetTick()` and `HAL_Delay()` stay correct, and SysTick wakes the core each
millisecond. Deeper modes (Stop2) would save more but need the clock tree
reconfigured on every wake and the IMU line set up as a wake-up source; that is
untested here.

Still initialized but unused by this firmware: `ADF1` (microphones),
`OCTOSPI1`, `OCTOSPI2` (external flash and PSRAM), `SPI2` (the Wi-Fi module),
`UCPD1` (USB-C power delivery), `USB_OTG_FS_PCD` (USB device) and `I2C1` — the
IMU is on `I2C2`. Each holds a peripheral clock, and the USB device block also
powers its transceiver. Removing them from the `.ioc` would cut current further;
they are left in place here because none of it has been measured on hardware.

`HAR_BLE_ENABLED` in `Core/Inc/har_ble.h` is 1 by default. Set it to 0 only to
free UART4 for an external module; `HAR_OUT_PORT` must then leave `HAR_OUT_BLE`.
The build refuses inconsistent combinations with an `#error`.

## Protocol

- Service UUID: `0000aabb-cc7a-482a-984a-7f2ed5b3e58f`
- Notification characteristic: `00003344-8e22-4541-9d4c-21edae82ed19`
- Advertised name: `Spokiy`

Over the radio a prediction is one UTF-8 line, newline-terminated:

```
<class index> <confidence> <t_ms>\n          e.g.   0 0.902 12748
```

13–14 bytes, so it fits a single notification. **Still concatenate
notification payloads until you see `\n` before parsing** — the code must not
assume one notification equals one line, or it will break the moment a
timestamp grows a digit or the format changes.

| field | meaning |
|---|---|
| class index | 0 `Lying`, 1 `Stationary`, 2 `Walking`, 3 `Running`, 4 `Stairs` |
| confidence | softmax probability of that class, three decimals |
| t_ms | milliseconds since the board booted — **not** wall-clock time |

The indices mirror `HAR_CLASS_LIST` in `Core/Inc/har_model_config.h`, and
`spokiy_app/frontend/src/predictions.ts` keeps the same list in `ACTIVITIES`.
Change one and you must change the other.

The compact form exists because the AT link to the module runs at 9600 baud:
see "Two defects this exposed" below for the measurement that forced it.

Over the **USB cable** the same prediction is printed in the older, readable
form, `# pred t=<ms> class=<Name> p=<0.000>\r\n`, because `tools/watch.py` and
`tools/log.py` parse that. `parsePrediction()` accepts both.

These UUIDs use ST's BLE_AT_Server custom UUID bases, not the predefined P2P
button service. The 16-bit parts (`aabb`, `3344`) are what the firmware passes
in `AT+BLE_SVC` and `AT+BLE_CHAR_ADD`; the rest of each UUID comes from the
BLE_AT_Server image on the module.

Service index 3 is the first custom service (`SRV_CUSTOM_APP_SVC_OFFSET` in
ST's driver), which is why the AT commands use `3,1`.

## Board preparation

1. Build and flash `activity_tracker_fw` to the STM32U585 using STM32CubeIDE,
   over the ST-Link USB port (CN8). This is the one step that needs a cable.
   Then fully power-cycle the board so both processors start cleanly.
2. Read the result. **Without a cable:** watch the LEDs as described above —
   green means success, a burst of `N` red blinks means step `N` failed.
   **With a cable:** open the ST-Link virtual COM port at 115200 baud and look
   for `# ble=ok step=0`. A `# ble=fail step=N` line identifies the first
   command that did not receive `OK`:

   | N | step |
   |---|---|
   | 1 | plain `AT` — the module did not answer at all |
   | 2 | `AT+BLE_NAME` |
   | 3 | `AT+BLE_INIT` |
   | 4 | `AT+BLE_SVC` — service registration |
   | 5 | `AT+BLE_CHAR_ADD` — characteristic registration |
   | 6 | `AT+BLE_ADV` — advertising |

   `ok` means the AT commands were acknowledged. It does not prove that the
   wireless stack completed each asynchronous operation.
3. With ST BLE Toolbox, scan for `Spokiy`, connect, discover the UUIDs above
   and enable notifications. Wait for an inference window. Disconnect the phone
   before connecting the website.
4. Run the app and connect in Chrome or Edge on a Bluetooth-capable computer.
   See `spokiy_app/README.md`.

## Measured on hardware, 18 Nov 2026

Verified end to end: the board advertises as `Spokiy`, a host connects, and
predictions arrive over the air once per second.

```
# at> AT+BLE_NAME=Spokiy                        → OK
# at> AT+BLE_INIT=1                             → OK
# at> AT+BLE_SVC=3,2,0xaabb,10                  → OK
# at> AT+BLE_CHAR_ADD=3,1,2,0x3344,20,0x10,0,0  → OK
# at> AT+BLE_ADV=1                              → OK
# ble=ok step=0 soft=0x00
```

Seen over the radio from a laptop BLE client:

```
Spokiy  00:80:E1:27:A2:AE          (00:80:E1 is STMicroelectronics' OUI)
  service 0000aabb-cc7a-482a-984a-7f2ed5b3e58f
     char 00003344-8e22-4541-9d4c-21edae82ed19  ['notify']
  raw 14 B: "0 0.902 12748"
```

55 consecutive lines were received over 55 s with no gaps, timestamps exactly
983 ms apart, across several re-advertise cycles.

### What the module actually needed

The STM32WB5MMG does **not** need an external ST-LINK, and it did not need
FUS or a wireless-stack install. Two findings made the difference.

**1. The on-board ST-LINK can reach the module.** Zephyr's board documentation
states it plainly: "The onboard ST-Link on the `b_u585i_iot02a` board can be
used to flash the STM32WB5MMG module. To do this you should put SW4 on OFF and
SW5 on ON mode." SW4 is labelled `SWD MCU`, SW5 is `SWD BLE`; each is a
two-pole DIP switch, one pole per SWD line. With them flipped, the programmer
reports `Device ID 0x495, STM32WB5x/35xx, Cortex-M4` instead of `0x482`.
Flip them back (SW4 ON, SW5 OFF) to return the ST-LINK to the STM32U585.

**2. The wireless stack was already installed.** The module's option bytes
show `SFSA = 0xCA (0x080CA000)`, `C2OPT = 1 (SBRV addresses Flash)` and
`SBRV = 0x32800`, i.e. CPU2 boots at 0x080CA000 — exactly where the BLE stack
lives. Only the CPU1 application was wrong: whatever was there answered `AT`
with `OK` and every `AT+BLE_*` with `ERROR`.

So the fix was a plain download of `BLE_AT_Server_reference.hex`
(0x08000000–0x0800BA73, far below the secure area) to the module, with no FUS
operation at all. The previous CPU1 image was read out first to
`backup_firmware_2026-11-18/wb_module_original.bin`.

### Two defects this exposed, both fixed

**Transmitting stole samples.** The verbose line
`# pred t=134975 class=Lying p=0.765` is 37 bytes, which the 9600-baud AT link
splits into three notifications. Each costs roughly 65 ms of blocking UART
plus the inter-chunk pause, while accelerometer samples arrive every 36 ms and
the IMU holds only the newest one. Measured effect: the rate collapsed from
27.4 Hz to **18.8 Hz with 972 missed samples**.

The radio now carries a compact line instead — `"<class index> <p> <t_ms>"`,
13–14 bytes, one notification — while the cable keeps the verbose format for
`tools/watch.py` and `tools/log.py`. The inter-chunk pause dropped from 40 ms
to 5 ms, and the `# rate=` diagnostics no longer go over the air.

Result: **26.4–26.6 Hz with exactly one missed sample per window** (39 missed
over 39 windows), down from 972. That one sample is interpolated by
`har_preproc_push_missed`, so the window still spans its full 2.0 s; one
sample in 27 is reconstructed rather than measured. Eliminating it entirely
would need the ISM330DHCX FIFO, so that blocking no longer loses anything.

**The board vanished after the first disconnect.** BLE_AT_Server does not
resume advertising once a client disconnects, and the event list has no
explicit disconnect event to hook. Verified: after one connection the device
was gone from every scan. The firmware now re-issues `AT+BLE_ADV=1` every
`HAR_BLE_READV_MS` (20 s) — one 16-character command, about 17 ms. Verified
that an active connection survives it and that the board reappears after a
disconnect.

### Also settled

`HAR_BLE_DRIVE_WAKE_PIN = 1` is correct: with PG6 driven high the module
answers `AT`, so the line is an active-high enable. UM2839 never loaded, so
this came from the board rather than the manual.

The STM32U585 side measures 27.4 Hz with `missed=0` when BLE is idle, against
the 27.45 Hz the model was trained on, and the sleeping main loop costs no
samples.

## Staying connectable, and what it cost

Getting one connection to work was not the same as staying connectable. Four
separate defects stood between the two, found by reading the board rather than
by reasoning about it.

**Events from the module were being lost.** UART4 was read only while waiting
for a command's reply, and the receiver holds a single byte. Everything the
module said between commands vanished — a connection event left nothing but a
stray `<` in the log. That is why the firmware never learned the client had
disconnected and never resumed advertising: **the board was findable exactly
once per power-up.** Fixed by an interrupt-driven receiver with a 256-byte ring
buffer (`UART4_IRQHandler`, `HAL_UART_RxCpltCallback` in `har_ble.c`).

**Lost bytes wedged the receiver.** An overrun sets the ORE flag, after which
the receiver stays dead until it is cleared. The earlier "the module went
silent after 19 minutes" was most likely our own receiver, not the module.
`HAL_UART_ErrorCallback` now clears ORE/NE/FE/PE and re-arms.

**`<OK` was not recognised.** When a fragment of a lost event was prepended to
a reply, the line no longer matched `OK`, so a perfectly good command waited
out its timeout. Leading `<` characters are now stripped before comparing.

**`AT+BLE_RST=1` at boot killed the module.** It was added to clear a phantom
connection, and it does restore advertising — but it leaves the stack
half-initialised, and the *first* client connection then kills the module
outright. The log shows it exactly: `<BLE_EVT_CONN=1` arrives, and from the
next command onwards there is not one byte, ever again. It is kept behind
`HAR_BLE_RESET_ON_BOOT`, default 0. **Do not turn it on.**

With those fixed, advertising is resumed from the event itself: the server
sends `<BLE_EVT_CONN=<status>`, and `status` 0 means the client left and
advertising stopped with it. One `AT+BLE_ADV=1` then, and only then. A
safety net re-issues it every `HAR_BLE_READV_SAFETY_MS` (5 min) if the event
was missed and no client is believed connected — deliberately rare, because
re-advertising blindly every 20 s is what killed the module the first time.

**Verified:** 12 consecutive connect/disconnect cycles, 4 then 8, over about
four minutes of continuous cycling. Every cycle found the board in the air,
connected, received predictions and disconnected. Afterwards the board was
still healthy: 15 AT exchanges, all `OK`, 26.4–26.6 Hz, one interpolated
sample per window.

### A crashed module can only be revived by removing power

This is a hard limit, not a shortcoming of the firmware. `WRLS_WKUP_B` (PG6)
is a wake signal, not a reset and not a power gate. Tested, all three failing:
a 50 ms low pulse, a 1 s pulse, and a 5 s pulse, plus a software reset of the
STM32U585. In every case the module stayed silent and `har_ble_init()`
returned `step=1`. Neither the module's `BOOT0` nor its `NRST` is wired to the
host, so there is nothing else to pull.

The firmware therefore does two things instead. It retries bring-up once with
a long pulse at boot, and then at most `HAR_BLE_REVIVE_TRIES` (5) times, once a
minute, in case the module is merely asleep rather than crashed. And when BLE
is down it stops talking to the module entirely, which restores the full
27.4 Hz sampling rate — measured: with BLE dead the rate returns to 27.4 Hz and
`missed` stops growing, so a dead radio never degrades the classification.

If the board is ever found silent on BLE with `# ble=fail step=1` on the cable,
the remedy is to remove power and reapply it. Nothing in software will do it.

## Failure handling during operation

A failed notification does **not** disable the channel. Until a client
subscribes to the characteristic, the server answers `ERROR`, which is the
expected state rather than a fault — disabling BLE on it would kill the link
before the browser ever connected.

After `HAR_BLE_FAIL_LIMIT` (3) consecutive failures the firmware pauses for
`HAR_BLE_BACKOFF_MS` (5000 ms) and re-issues `AT+BLE_ADV=1`, in case the module
restarted. The pause exists because a silent module would otherwise spend more
time in UART timeouts than one window hop lasts (~0.98 s at 27.45 Hz), starving
inference.

Notification chunking never emits a one-byte tail: ST's own client encodes a
single byte as a decimal number rather than a `0x` string, so an 18 + 1 split
becomes 17 + 2. The single-byte decimal form is implemented too, for payloads
that are genuinely one byte.

## Known limits

AT operations are synchronous, so BLE transmissions can cause missed IMU
samples. The firmware reports `# rate` and `missed` on USB, so measuring this
needs one cabled run; afterwards the board can be untethered. The server
schedules GATT operations asynchronously, so command acknowledgements do not
establish radio delivery.

CSV streaming (`HAR_STREAM_CSV`) cannot use BLE — one line per sample at
27.45 Hz far exceeds a 9600-baud AT channel. Switch `HAR_OUT_PORT` to
`HAR_OUT_STLINK` to collect CSV; the build enforces this with an `#error`.

**Not yet verified on hardware:** the module firmware, the wake-pin polarity,
radio delivery, disconnect/reconnect behaviour, long-running operation and
inference timing all need board tests. For iPhone, ST BLE Toolbox can inspect
notifications, but the website's Web Bluetooth flow needs a supported desktop
browser.
