import win32api
import win32con
import win32gui
import numpy as np
import ultralytics
import threading
import math
import time
import cv2
import mss

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

PICO_VID = 0x239A

def find_pico_port():
    if serial is None:
        return None
    for port in serial.tools.list_ports.comports():
        if port.vid == PICO_VID:
            return port.device
    return None


class PicoMouse:

    def __init__(self, port, baud=115200):
        self.ser = serial.Serial(port, baud, timeout=0)

    def move(self, dx, dy):
        if dx or dy:
            self.ser.write(("%d,%d\n" % (int(dx), int(dy))).encode())

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def DetectMonitor():
    cursorX, cursorY = win32api.GetCursorPos()
    with mss.mss() as sct:
        monitors = sct.monitors[1:]
        for index, mon in enumerate(monitors, start=1):
            inX = mon["left"] <= cursorX < mon["left"] + mon["width"]
            inY = mon["top"] <= cursorY < mon["top"] + mon["height"]
            if inX and inY:
                print(f"Monitor em uso: #{index} -> "
                      f"{mon['width']}x{mon['height']} "
                      f"(offset {mon['left']},{mon['top']})")
                return index, mon

    with mss.mss() as sct:
        mon = sct.monitors[1]
    print(f"Monitor nao identificado pelo cursor; usando primario: "
          f"{mon['width']}x{mon['height']} (offset {mon['left']},{mon['top']})")
    return 1, mon


class Config:
    def __init__(self):

        self.monitor_index, monitor = DetectMonitor()
        self.monitor_left = monitor["left"]
        self.monitor_top = monitor["top"]
        self.width = monitor["width"]
        self.height = monitor["height"]

        self.center_x = self.monitor_left + self.width // 2
        self.center_y = self.monitor_top + self.height // 2

        self.capture_width = 120
        self.capture_height = 170
        self.capture_left = self.center_x - self.capture_width // 2
        self.capture_top = self.center_y - self.capture_height // 2
        self.crosshairX = self.capture_width // 2
        self.crosshairY = self.capture_height // 2

        self.region = {"top": self.capture_top,"left": self.capture_left,"width": self.capture_width,"height": self.capture_height+100}

        self.Running = True
        self.AimToggle = True
        self.Sensitivity = 1
        self.MovementCoefficientX = 0.80
        self.MovementCoefficientY = 0.65
        self.delay = 0.007
        self.radius = 60          # FOV
        self.smooth = 5.0

        self.use_pico = True
        self.pico_port = find_pico_port()


config = Config()


def menu():
    options = {
        "1": ("FOV (raio em pixels)", "radius", int, "max " + str(config.capture_width // 2)),
        "2": ("Smooth (1 = snap, maior = mais suave)", "smooth", float, ">= 1"),
        "3": ("Sensibilidade ingame", "Sensitivity", float, "> 0"),
        "4": ("Delay entre movimentos (s)", "delay", float, "ex: 0.007"),
        "5": ("Coeficiente de movimento X", "MovementCoefficientX", float, ""),
        "6": ("Coeficiente de movimento Y", "MovementCoefficientY", float, ""),
    }

    while config.Running:
        print("\n" + "=" * 44)
        print("           AIMBOT - MENU")
        print("=" * 44)
        print(f"  Monitor em uso : #{config.monitor_index} "
              f"({config.width}x{config.height})")
        print(f"  Aim ligado     : {'SIM' if config.AimToggle else 'NAO'}")
        if config.use_pico:
            print(f"  Movimento      : Pico/HID ({config.pico_port})")
        else:
            print(f"  Movimento      : win32 (software)")
        print("-" * 44)
        for key, (label, attr, _cast, hint) in options.items():
            value = getattr(config, attr)
            hint_str = f"  [{hint}]" if hint else ""
            print(f"  [{key}] {label}: {value}{hint_str}")
        print("  [t] Ligar/desligar aim")
        print("  [q] Sair")
        print("=" * 44)

        choice = input("Escolha uma opcao: ").strip().lower()

        if choice == "q":
            config.AimToggle = False
            config.Running = False
            print("Encerrando...")
            break
        elif choice == "t":
            config.AimToggle = not config.AimToggle
            print(f"Aim agora esta: {'LIGADO' if config.AimToggle else 'DESLIGADO'}")
        elif choice in options:
            label, attr, cast, _hint = options[choice]
            raw = input(f"Novo valor para '{label}': ").strip().replace(",", ".")
            try:
                value = cast(raw)
                if attr == "smooth" and value < 1:
                    value = 1.0
                if attr == "radius":
                    value = max(1, min(value, config.capture_width // 2))
                if attr == "Sensitivity" and value <= 0:
                    print("Sensibilidade precisa ser > 0. Ignorado.")
                    continue
                setattr(config, attr, value)
                print(f"OK -> {label} = {value}")
            except ValueError:
                print("Valor invalido, tente de novo.")
        else:
            print("Opcao invalida.")


def aim_loop():

    indexMin = 0

    x1=y1=x2=y2=0

    #model = ultralytics.YOLO("Fortnite by hogthewog.onnx", task = 'detect')
    model = ultralytics.YOLO("yolov8n.pt")
    screenCapture = mss.mss()

    pico = None
    if config.use_pico:
        if serial is None:
            print("pyserial nao instalado (pip install pyserial). Usando win32.")
            config.use_pico = False
        elif not config.pico_port:
            print("Pico nao encontrado em nenhuma COM. Usando win32.")
            config.use_pico = False
        else:
            try:
                pico = PicoMouse(config.pico_port)
                print(f"Pico conectado em {config.pico_port} (movimento via HID).")
            except Exception as e:
                print(f"Falha ao abrir {config.pico_port}: {e}. Usando win32.")
                config.use_pico = False

    while config.Running:
        time.sleep(0.001)

        if config.AimToggle == False:
                time.sleep(0.1)
                continue

        GameFrame = np.array(screenCapture.grab(config.region))
        GameFrame = cv2.cvtColor(GameFrame, cv2.COLOR_BGRA2BGR)
        results = model.predict(source = GameFrame, conf = 0.5, classes=[0], verbose=False, max_det = 10)
        boxes = results[0].boxes.xyxy

        distsm = 99999
        for i in range(len(boxes)):
            x1, y1, x2, y2 = boxes[i].tolist()
            moveX = int(((x2 - x1) // 2+x1 - config.crosshairX))
            moveY = int((y1+(y2 - y1) * 0.085 - config.crosshairY))
            distance = math.sqrt(math.pow(moveX, 2) + math.pow(moveY, 2))
            if distsm > distance:
                distsm = distance
                indexMin = i

        if len(boxes) > 0:
            x1, y1, x2, y2 = boxes[indexMin].tolist()
            deltaX = (((x2 - x1) // 2 + x1 - config.crosshairX)) / config.Sensitivity
            deltaY = ((y1 + (y2 - y1) * 0.085 - config.crosshairY)) / config.Sensitivity
            distance = math.sqrt(deltaX ** 2 + deltaY ** 2)

            if distance < config.radius:
                smooth = config.smooth if config.smooth >= 1 else 1.0
                moveX = int((deltaX / smooth) * config.MovementCoefficientX)
                moveY = int((deltaY / smooth) * config.MovementCoefficientY)
                if moveX != 0 or moveY != 0:
                    if config.use_pico and pico is not None:
                        pico.move(moveX, moveY)
                    else:
                        win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, moveX, moveY, 0, 0)
                    time.sleep(config.delay)

       #FOR DEBUGGING
            #cv2.rectangle(GameFrame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
        #cv2.imshow("Game Frame", GameFrame)
        #if cv2.waitKey(1) & 0xFF == ord('q'):
            #config.Running = False
            #break
    cv2.destroyAllWindows()


def main():
    aimThread = threading.Thread(target=aim_loop, daemon=True)
    aimThread.start()
    menu()
    aimThread.join(timeout=2)


if __name__ == "__main__":
    main()
