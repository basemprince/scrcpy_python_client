"""Control protocol utilities for the scrcpy Python client."""

import socket
import struct
import threading
from typing import Optional, Tuple

# Message types (subset)
CONTROL_MSG_TYPE_INJECT_KEYCODE = 0
CONTROL_MSG_TYPE_INJECT_TEXT = 1
CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT = 2
CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT = 3
CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON = 4
CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL = 5
CONTROL_MSG_TYPE_EXPAND_SETTINGS_PANEL = 6
CONTROL_MSG_TYPE_COLLAPSE_PANELS = 7

# Touch actions
AMOTION_EVENT_ACTION_DOWN = 0
AMOTION_EVENT_ACTION_UP = 1
AMOTION_EVENT_ACTION_MOVE = 2

AMOTION_EVENT_BUTTON_PRIMARY = 1 << 0
AMOTION_EVENT_BUTTON_SECONDARY = 1 << 1
AMOTION_EVENT_BUTTON_TERTIARY = 1 << 2

SC_POINTER_ID_MOUSE = -1 & 0xFFFFFFFFFFFFFFFF

# Map pygame key constants to Android key codes (partial)
try:
    import pygame

    ANDROID_KEYCODES = {
        pygame.K_a: 29,
        pygame.K_b: 30,
        pygame.K_c: 31,
        pygame.K_d: 32,
        pygame.K_e: 33,
        pygame.K_f: 34,
        pygame.K_g: 35,
        pygame.K_h: 36,
        pygame.K_i: 37,
        pygame.K_j: 38,
        pygame.K_k: 39,
        pygame.K_l: 40,
        pygame.K_m: 41,
        pygame.K_n: 42,
        pygame.K_o: 43,
        pygame.K_p: 44,
        pygame.K_q: 45,
        pygame.K_r: 46,
        pygame.K_s: 47,
        pygame.K_t: 48,
        pygame.K_u: 49,
        pygame.K_v: 50,
        pygame.K_w: 51,
        pygame.K_x: 52,
        pygame.K_y: 53,
        pygame.K_z: 54,
        pygame.K_0: 7,
        pygame.K_1: 8,
        pygame.K_2: 9,
        pygame.K_3: 10,
        pygame.K_4: 11,
        pygame.K_5: 12,
        pygame.K_6: 13,
        pygame.K_7: 14,
        pygame.K_8: 15,
        pygame.K_9: 16,
        pygame.K_SPACE: 62,
        pygame.K_RETURN: 66,
        pygame.K_BACKSPACE: 67,
        pygame.K_TAB: 61,
        pygame.K_ESCAPE: 111,
        pygame.K_LEFT: 21,
        pygame.K_RIGHT: 22,
        pygame.K_UP: 19,
        pygame.K_DOWN: 20,
        # Additional keycodes
        pygame.K_F1: 3,  # HOME
        pygame.K_F2: 4,  # BACK
        pygame.K_F3: 187,  # APP_SWITCH
        pygame.K_F4: 82,  # MENU
        pygame.K_F5: 26,  # POWER
    }

    MOUSE_BUTTON_MAP = {
        1: AMOTION_EVENT_BUTTON_PRIMARY,
        2: AMOTION_EVENT_BUTTON_TERTIARY,
        3: AMOTION_EVENT_BUTTON_SECONDARY,
    }
except Exception:  # pragma: no cover - pygame not available
    ANDROID_KEYCODES = {}
    MOUSE_BUTTON_MAP = {}


class Control:
    """Encapsulates the control protocol."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.thread: Optional[threading.Thread] = None
        self.resolution: Optional[Tuple[int, int]] = None
        self.mouse_buttons = 0

    # ------------------------------------------------------------------
    # Device <-> client communication
    def start(self) -> None:
        """Start the control protocol thread."""
        self.thread = threading.Thread(target=self._device_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop the control protocol thread and close the socket."""
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.sock.close()
            self.sock = None  # type: ignore[assignment]
        if self.thread:
            self.thread.join(timeout=1)
            self.thread = None

    def set_resolution(self, resolution: Tuple[int, int]) -> None:
        """Set the resolution of the device."""
        self.resolution = resolution

    def _device_loop(self) -> None:
        """Main loop to handle messages from the device."""
        try:
            while True:
                msg_type_raw = self.sock.recv(1)
                if not msg_type_raw:
                    break
                msg_type = msg_type_raw[0]
                print(f"Device message type {msg_type}")
                if msg_type == 0:  # DEVICE_MSG_TYPE_CLIPBOARD
                    length_bytes = self.sock.recv(4)
                    if not length_bytes:
                        break
                    length = struct.unpack(">I", length_bytes)[0]
                    text = self.sock.recv(length).decode("utf-8")
                    print("Device clipboard:", text)
                elif msg_type == 1:  # DEVICE_MSG_TYPE_ACK_CLIPBOARD
                    self.sock.recv(8)
                elif msg_type == 2:  # DEVICE_MSG_TYPE_UHID_OUTPUT
                    hdr = self.sock.recv(4)
                    if not hdr:
                        break
                    ident, size = struct.unpack(">HH", hdr)
                    self.sock.recv(size)
                    print(f"UHID output id={ident} size={size}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Sending helpers
    def send_text(self, text: str) -> None:
        """Inject text into the device."""
        if not self.sock:
            return
        payload = text.encode("utf-8")
        msg = struct.pack(">BI", CONTROL_MSG_TYPE_INJECT_TEXT, len(payload)) + payload
        self.sock.sendall(msg)
        print(f"Sent text: {text}")

    def inject_keycode(self, keycode: int, action: int, repeat: int = 0, meta: int = 0) -> None:
        """Inject a keycode into the device."""
        if not self.sock:
            return
        msg = struct.pack(
            ">BBIII",
            CONTROL_MSG_TYPE_INJECT_KEYCODE,
            action,
            keycode,
            repeat,
            meta,
        )
        self.sock.sendall(msg)
        print(f"Sent keycode {keycode} action {action}")

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def inject_touch(
        self,
        action: int,
        x: int,
        y: int,
        pressure: float,
        action_button: int,
        buttons: int,
    ) -> None:
        """Inject a touch event into the device."""
        if not self.sock or not self.resolution:
            return
        width, height = self.resolution
        p = int(max(0.0, min(1.0, pressure)) * 0x10000)
        if p > 0xFFFF:  # pylint: disable=consider-using-min-builtin
            p = 0xFFFF
        msg = struct.pack(
            ">BBQiiHHHII",
            CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
            action,
            SC_POINTER_ID_MOUSE,
            x,
            y,
            width,
            height,
            p,
            action_button,
            buttons,
        )
        self.sock.sendall(msg)
        print(f"Touch {action} at ({x},{y}) pressure={pressure:.2f} btn={action_button} buttons={buttons}")

    def back_or_screen_on(self, action: int) -> None:
        """Send a back or screen on action to the device."""
        if not self.sock:
            return
        msg = struct.pack(">BB", CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON, action)
        self.sock.sendall(msg)
        print(f"BACK_OR_SCREEN_ON action {action}")

    def expand_notification_panel(self) -> None:
        """Expand the notification panel on the device."""
        if self.sock:
            self.sock.sendall(struct.pack(">B", CONTROL_MSG_TYPE_EXPAND_NOTIFICATION_PANEL))
            print("Expand notification panel")

    def collapse_panels(self) -> None:
        """Collapse the notification and settings panels on the device."""
        if self.sock:
            self.sock.sendall(struct.pack(">B", CONTROL_MSG_TYPE_COLLAPSE_PANELS))
            print("Collapse panels")
