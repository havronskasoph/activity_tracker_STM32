# Прошивання BLE-модуля STM32WB5MMG

**Статус: зроблено 18.11.2026. Модуль працює, плата рекламує себе як `Spokiy`.**

Цей файл лишається як опис того, що саме було зроблено, і як повторити, якщо
модуль колись доведеться перепрошити.

## Головне: зовнішній програматор НЕ потрібен

Перша редакція цього файлу стверджувала, що вбудований ST-LINK до модуля не
дотягується і потрібен зовнішній програматор на роз'єм CN5. **Це було
неправильно.**

Вбудований ST-LINK уміє прошивати STM32WB5MMG — його треба лише на нього
перемкнути двома перемикачами на зворотному боці плати:

| перемикач | підпис на платі | до модуля | назад до U585 |
|---|---|---|---|
| **SW4** | `SWD MCU` | OFF | ON |
| **SW5** | `SWD BLE` | ON | OFF |

Кожен з них здвоєний — по два повзунки, бо SWD складається з двох ліній
(`SWCLK` і `SWDIO`). Рухаються всі чотири повзунки, попарно.

Перевірка, що влучили: програматор має показати `Device ID 0x495,
STM32WB5x/35xx, Cortex-M4` замість `0x482, STM32U575/STM32U585`.

```
STM32_Programmer_CLI.exe -c port=SWD mode=HOTPLUG
```

Джерело: документація Zephyr для плати `b_u585i_iot02a` — «The onboard ST-Link
on the b_u585i_iot02a board can be used to flash the STM32WB5MMG module. To do
this you should put SW4 on OFF and SW5 on ON mode.»

## Друге: FUS і стек BLE не знадобилися

Стек BLE у модулі **вже був установлений із заводу**. Це видно з байтів опцій:

```
SFSA  : 0xCA  (0x80CA000)        захищена область — там лежить стек
C2OPT : 0x1   (SBRV addresses Flash)
SBRV  : 0x32800                  CPU2 стартує з 0x080CA000
```

Бракувало тільки застосунку на ядрі CPU1: там стояло щось, що відповідало
`OK` на просту команду `AT` і `ERROR` на всі `AT+BLE_*`, включно з читанням
власної Bluetooth-адреси.

Тому з трьох файлів знадобився **лише один** — `BLE_AT_Server_reference.hex`.
Це звичайний запис у незахищену область (`0x08000000`–`0x0800BA73`), жодних
операцій FUS.

```
STM32_Programmer_CLI.exe -c port=SWD mode=UR -d BLE_AT_Server_reference.hex -v
STM32_Programmer_CLI.exe -c port=SWD mode=UR -rst
```

Попередній вміст CPU1 збережено перед записом:
`backup_firmware_2026-11-18/wb_module_original.bin` (64 КБ, з `0x08000000`).

## Файли

| файл | що це | знадобився? |
|---|---|---|
| `BLE_AT_Server_reference.hex` | застосунок CPU1, приймає AT-команди | **так** |
| `stm32wb5x_BLE_Stack_full_fw.bin` | стек BLE для CPU2 | ні — уже стояв |
| `stm32wb5x_FUS_fw.bin` | Firmware Upgrade Services | ні |

Усі з офіційного репозиторію ST: https://github.com/STMicroelectronics/STM32CubeWB

Якщо колись доведеться ставити стек заново, знадобиться **окремий**
STM32CubeProgrammer: той, що вбудований у STM32CubeIDE, не містить файла
`0x495_FUS_Operator.bin`, без якого команди FUS не працюють.

## Порядок дій цілком

1. `SW4` → OFF, `SW5` → ON.
2. Перевірити, що видно `Device ID 0x495`.
3. Прочитати копію: `-c port=SWD mode=UR -u 0x08000000 0x10000 backup.bin`.
4. Залити `BLE_AT_Server_reference.hex`, перевірити, скинути.
5. `SW4` → ON, `SW5` → OFF.
6. Скинути плату, у виводі має бути `# ble=ok step=0 soft=0x00`.
7. Будь-яким сканером BLE знайти `Spokiy`.

Решта — у `project/activity_tracker_STM32/firmware/BLE_SETUP.md`: протокол,
UUID'и, формат даних і два дефекти, які виявилися під час перевірки на платі.
