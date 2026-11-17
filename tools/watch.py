#!/usr/bin/env python3
r"""Показує, що видає плата: клас, імовірність, фактичну частоту.

Потрібен pyserial:  pip install pyserial

Запуск із кореня репозиторію:
    python tools/watch.py              # порт визначається сам
    python tools/watch.py COM7         # якщо не визначився

Плата має бути підключена USB-кабелем. Прошивка стартує сама, кнопок
натискати не треба; перший рядок з'явиться через дві секунди після подачі
живлення — платі треба набрати перше вікно.

Якщо потрібен сирий потік даних для запису в CSV, у прошивці слід увімкнути
HAR_STREAM_CSV 1 (Core/Src/main.c), перезібрати й прошити, а записувати
через tools/log.py.
"""
import sys
import serial
from serial.tools import list_ports

BAUD = 115200


def find_port():
    for p in list_ports.comports():
        if "STLink" in (p.description or "") or "ST-Link" in (p.description or ""):
            return p.device
    return None


port = sys.argv[1] if len(sys.argv) > 1 else find_port()
if not port:
    sys.exit("ST-Link не знайдено. Перевір, чи плата підключена, "
             "або вкажи порт: tools/watch.py COM5")

print(f"слухаю {port} на {BAUD} бод, Ctrl+C щоб зупинити\n")
ser = serial.Serial(port, BAUD, timeout=1)
try:
    while True:
        line = ser.readline().decode("utf-8", "replace").rstrip()
        if not line:
            continue
        if line.startswith("# pred"):
            parts = dict(p.split("=", 1) for p in line[7:].split() if "=" in p)
            cls = parts.get("class", "?")
            prob = float(parts.get("p", 0))
            bar = "#" * int(prob * 30)
            print(f"  {cls:<12s} {prob:5.3f}  {bar}")
        elif line.startswith("# rate"):
            print(f"\n  [{line[2:]}]\n")
        elif line.startswith("#"):
            print(f"  {line[2:]}")
        else:
            print(f"  {line}")
except KeyboardInterrupt:
    print("\nзупинено")
finally:
    ser.close()
