import sys, time, serial   # pip install pyserial
from serial.tools import list_ports

if len(sys.argv) != 4:
    sys.exit("usage: python tools/log.py <COM5|auto> <label> <person>")
port, label, person = sys.argv[1], sys.argv[2], sys.argv[3]  # COM5 walking p1


def stlink_port():
    """COM name of the ST-LINK VCP (USB 0483:374E), or None if not plugged in."""
    for p in list_ports.comports():
        if "0483:374E" in (p.hwid or "").upper():
            return p.device
        if "STLINK" in (p.description or "").upper().replace("-", ""):
            return p.device
    return None


def resolve(requested, timeout=180):
    """Wait for the board; the VCP may come back under a different COM number."""
    deadline, dots = time.time() + timeout, False
    while time.time() < deadline:
        if requested.lower() != "auto":
            if requested in [p.device for p in list_ports.comports()]:
                return requested
        found = stlink_port()
        if found:
            if requested.lower() != "auto" and found != requested:
                print(f"\n{requested} is gone, using {found} instead")
            return found
        if not dots:
            print("waiting for the board (USB-C in CN8)", end="", flush=True)
            dots = True
        print(".", end="", flush=True)
        time.sleep(1)
    sys.exit(f"\nno ST-LINK serial port within {timeout}s - check that the "
             "cable carries data and sits in CN8")


def connect(requested):
    """Open the port, waiting out a port still held by CubeIDE or a terminal."""
    while True:
        name = resolve(requested)
        try:
            return name, serial.Serial(name, 115200, timeout=1)
        except serial.SerialException as e:
            print(f"\ncannot open {name}: {e.__class__.__name__} - close any "
                  "terminal or debug session holding it, retrying")
            time.sleep(2)


fname = f"data/{label}_{person}_{time.strftime('%H%M%S')}.csv"
name, ser = connect(port)
print(f"logging {name} -> {fname}   (Ctrl+C to stop)")

n, run_n, first, last = 0, 0, None, -1
with open(fname, "w", buffering=1) as f:   # line buffered: nothing is lost if killed
    f.write("timestamp_ms,ax,ay,az\n")
    try:
        while True:
            try:
                line = ser.readline().decode(errors="ignore").strip()
            except serial.SerialException:
                # the VCP drops out when the board is reset or reflashed
                print(f"\nlost {name}, reconnecting")
                try:
                    ser.close()
                except Exception:
                    pass
                name, ser = connect(port)
                continue
            if line.startswith("#"):          # firmware notices, e.g. "# missed 3"
                print(f"\n{line}")
                continue
            parts = line.split(",")
            if len(parts) != 4:
                continue
            try:
                [float(p) for p in parts]
            except ValueError:
                continue
            f.write(line + "\n")
            n += 1
            t = int(parts[0])
            if first is None or t < last:      # board restarted: start a new run
                first, run_n = t, 0
            last, run_n = t, run_n + 1
            if n % 26 == 0:
                print(f"{n} samples", end="\r")
    except KeyboardInterrupt:
        pass

print(f"\nSaved {n} samples to {fname}")
if run_n > 1:
    span = (last - first) / 1000
    print(f"last run: {run_n} samples over {span:.1f} s = {(run_n - 1) / span:.2f} Hz")
