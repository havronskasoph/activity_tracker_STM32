import sys, time, serial   # pip install pyserial

port, label, person = sys.argv[1], sys.argv[2], sys.argv[3]  # COM3 walking p1
fname = f"data/{label}_{person}_{time.strftime('%H%M%S')}.csv"

ser = serial.Serial(port, 115200, timeout=1)
n = 0
with open(fname, "w") as f:
    f.write("timestamp_ms,ax_mg,ay_mg,az_mg,gx_mdps,gy_mdps,gz_mdps\n")
    try:
        while True:
            line = ser.readline().decode(errors="ignore").strip()
            parts = line.split(",")
            if len(parts) == 7 and all(p.lstrip("-").isdigit() for p in parts):
                f.write(line + "\n"); n += 1
                if n % 26 == 0: print(f"{n} samples", end="\r")
    except KeyboardInterrupt:
        print(f"\nSaved {n} samples to {fname}")
