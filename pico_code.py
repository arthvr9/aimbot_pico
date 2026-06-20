import sys
import usb_hid
import supervisor
import board
import digitalio
from adafruit_hid.mouse import Mouse

mouse = Mouse(usb_hid.devices)

led = digitalio.DigitalInOut(board.GP25)
led.direction = digitalio.Direction.OUTPUT
led.value = True

buf = ""

while True:
    if supervisor.runtime.serial_bytes_available:
        ch = sys.stdin.read(1)
        if ch in ("\n", "\r"):
            line = buf.strip()
            buf = ""
            if line:
                try:
                    parts = line.split(",")
                    dx = int(parts[0])
                    dy = int(parts[1])
                    mouse.move(x=dx, y=dy)
                except (ValueError, IndexError):
                    pass
        else:
            buf += ch
