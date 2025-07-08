import argparse
import socket
import struct
import subprocess
import time
import av
import pygame
import os
import threading
from typing import Optional, Tuple
import numpy as np

CODECS = {
    0x68323634: 'h264',
    0x68323635: 'hevc',
    0x00617631: 'av1',
}

HEADER_SIZE = 12
FLAG_CONFIG = 1 << 63
FLAG_KEY_FRAME = 1 << 62
PTS_MASK = FLAG_KEY_FRAME - 1

SERVER_VERSION = "3.3.1"
DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
LOCK_SCREEN_ORIENTATION_UNLOCKED = 0


def read_exact(sock: socket.socket, length: int) -> bytes:
    buf = bytearray()
    while len(buf) < length:
        chunk = sock.recv(length - len(buf))
        if not chunk:
            raise EOFError("socket closed")
        buf.extend(chunk)
    return bytes(buf)


class Client:
    def __init__(
        self,
        *,
        adb: str = "adb",
        server: str = "scrcpy-server-v3.3.1",
        host: str = "127.0.0.1",
        port: int = 27183,
        ip: str = "127.0.0.1:5037",
        max_width: int = 1440,
        bitrate: int = 8_000_000,
        max_fps: int = 0,
        flip: bool = False,
        stay_awake: bool = True,
        lock_screen_orientation: int = LOCK_SCREEN_ORIENTATION_UNLOCKED,
        docker: bool = False,
    ) -> None:
        self.server = server
        self.host = host
        self.port = port
        self.max_width = max_width
        self.bitrate = bitrate
        self.max_fps = max_fps
        self.flip = flip
        self.stay_awake = stay_awake
        self.lock_screen_orientation = lock_screen_orientation
        self.docker = docker

        adb_host, sep, adb_port = ip.partition(":")
        self.adb_cmd = [adb]
        if sep:
            self.adb_cmd += ["-H", adb_host, "-P", adb_port]

        self.proc: subprocess.Popen | None = None
        self.last_frame: Optional[np.ndarray] = None
        self.resolution: Optional[Tuple[int, int]] = None
        self.device_name: Optional[str] = None
        self.thread: Optional[threading.Thread] = None

        self.run()

    def _start_server(self) -> None:
        server_file_path = os.path.join(
            os.path.abspath(os.path.dirname(__file__)), self.server
        )
        subprocess.run(self.adb_cmd + ["push", server_file_path, DEVICE_SERVER_PATH], check=True)
        subprocess.run(self.adb_cmd + ["forward", f"tcp:{self.port}", "localabstract:scrcpy"], check=True)

        cmd = self.adb_cmd + [
            "shell",
            f"CLASSPATH={DEVICE_SERVER_PATH}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SERVER_VERSION,
            "tunnel_forward=true",
            "audio=false",
            "control=false",
            "cleanup=false",
        ]
        if self.max_width:
            cmd.append(f"max_size={self.max_width}")
        if self.bitrate:
            cmd.append(f"video_bit_rate={self.bitrate}")
        if self.max_fps:
            cmd.append(f"max_fps={self.max_fps}")
        if self.flip:
            cmd.append("orientation=flip")
        if self.stay_awake:
            cmd.append("stay_awake=true")
        if self.lock_screen_orientation != LOCK_SCREEN_ORIENTATION_UNLOCKED:
            cmd.append(f"lock_screen_orientation={self.lock_screen_orientation}")

        self.proc = subprocess.Popen(cmd)

    def _stop_server(self) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait()
        subprocess.run(self.adb_cmd + ["forward", "--remove", f"tcp:{self.port}"], check=True)

    def run(self) -> None:
        self._start_server()
        time.sleep(1)
        self.thread = threading.Thread(target=self._video_loop, daemon=True)
        self.thread.start()

    def _video_loop(self) -> None:
        try:
            with socket.create_connection((self.host, self.port)) as sock:
                _ = read_exact(sock, 1)
                self.device_name = read_exact(sock, 64).split(b"\0", 1)[0].decode()

                raw_codec = struct.unpack('>I', read_exact(sock, 4))[0]
                self.resolution = struct.unpack('>II', read_exact(sock, 8))
                width, height = self.resolution
                codec_name = CODECS.get(raw_codec)
                if not codec_name:
                    raise RuntimeError(f"Unsupported codec id: {raw_codec:#x}")

                print(f"Connected to '{self.device_name}': codec={codec_name} size={width}x{height}")

                decoder = av.CodecContext.create(codec_name, "r")
                config_data = b""

                while True:
                    header = read_exact(sock, HEADER_SIZE)
                    pts_flags, size = struct.unpack('>QI', header)
                    packet_data = read_exact(sock, size)

                    if pts_flags & FLAG_CONFIG:
                        config_data = packet_data
                        continue

                    if config_data:
                        packet_data = config_data + packet_data
                        config_data = b""

                    packet = av.Packet(packet_data)
                    packet.pts = pts_flags & PTS_MASK
                    if pts_flags & FLAG_KEY_FRAME:
                        try:
                            packet.is_keyframe = True
                        except AttributeError:
                            pass

                    for frame in decoder.decode(packet):
                        img = frame.to_ndarray(format="rgb24")
                        self.last_frame = img

        finally:
            self._stop_server()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='scrcpy minimal client')
    parser.add_argument('--adb', default='adb', help='adb executable')
    parser.add_argument('--server', default='scrcpy-server-v3.3.1', help='path to scrcpy-server.jar')
    parser.add_argument('--host', default='127.0.0.1', help='host to connect to')
    parser.add_argument('--port', type=int, default=27183, help='local TCP port')
    parser.add_argument('--adb-host', default='127.0.0.1:5037', help='adb server host:port')
    args = parser.parse_args()

    client = Client(adb=args.adb, server=args.server, host=args.host, port=args.port, ip=args.adb_host)

    # GUI must be handled in main thread
    pygame.init()
    screen = None
    clock = pygame.time.Clock()

    try:
        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise KeyboardInterrupt

            if client.last_frame is not None:
                frame = client.last_frame
                h, w, _ = frame.shape

                if screen is None:
                    screen = pygame.display.set_mode((w, h))

                surf = pygame.image.frombuffer(frame.tobytes(), (w, h), "RGB")
                screen.blit(surf, (0, 0))
                pygame.display.flip()

            clock.tick(60)

    except KeyboardInterrupt:
        print("Exiting...")
        pygame.quit()
