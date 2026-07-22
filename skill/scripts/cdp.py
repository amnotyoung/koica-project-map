"""최소 Chrome DevTools Protocol 클라이언트 (표준 라이브러리만).

`--screenshot` 플래그는 load 이벤트 직후에 찍는다. MapLibre 처럼 **로드 뒤에도
타일을 받아 계속 그리는** 페이지에는 못 쓴다(--virtual-time-budget 은 워커의
네트워크 요청을 기다리지 않아 백지가 나온다).

그래서 조건이 참이 될 때까지 기다렸다가 찍는다:

    shot("file:///map.html", Path("out.png"), 1600, 1100, 2,
         ready_js="document.title==='MAP_READY'")

websockets 패키지를 쓰지 않는 이유는 스킬을 표준 라이브러리로 유지하기 위해서다.
프레임 처리는 텍스트 프레임 송수신에 필요한 최소 범위만 구현한다.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from common import log


class WS:
    """CDP 용 최소 WebSocket 클라이언트 (텍스트 프레임만)."""

    def __init__(self, url: str, timeout: float = 60.0):
        _, rest = url.split("://", 1)
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        if b"101" not in buf.split(b"\r\n", 1)[0]:
            raise RuntimeError("WebSocket 업그레이드 실패")
        self.rest = buf.split(b"\r\n\r\n", 1)[1]
        self._id = 0

    def send(self, method: str, params: dict | None = None) -> int:
        self._id += 1
        payload = json.dumps({"id": self._id, "method": method,
                              "params": params or {}}).encode()
        mask = os.urandom(4)
        n = len(payload)
        head = b"\x81"
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + masked)
        return self._id

    def _read(self, n: int) -> bytes:
        while len(self.rest) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("연결이 끊겼습니다")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def recv(self) -> dict:
        while True:
            b1, b2 = self._read(2)
            opcode, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data = self._read(n)
            if opcode == 0x1:
                return json.loads(data)
            if opcode == 0x8:
                raise ConnectionError("서버가 연결을 닫았습니다")

    def call(self, method: str, params: dict | None = None, timeout: float = 60.0):
        mid = self.send(method, params)
        end = time.time() + timeout
        while time.time() < end:
            msg = self.recv()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f'{method}: {msg["error"].get("message")}')
                return msg.get("result", {})
        raise TimeoutError(method)

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def shot(url: str, out: Path, width: int, height: int, scale: int = 2,
         ready_js: str | None = None, chrome: str | None = None,
         wait: float = 60.0) -> Path:
    """페이지를 열고 ready_js 가 참이 되면 스크린샷을 찍는다."""
    from export import find_chrome
    chrome = chrome or find_chrome()
    port = _free_port()
    tmp = tempfile.mkdtemp()
    proc = subprocess.Popen(
        [chrome, "--headless=new", "--no-sandbox", "--no-first-run",
         "--no-default-browser-check", "--hide-scrollbars",
         "--use-gl=swiftshader", "--enable-unsafe-swiftshader",
         f"--remote-debugging-port={port}", f"--user-data-dir={tmp}",
         f"--window-size={width},{height}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        ws_url = _wait_debugger(port, timeout=25)
        ws = WS(ws_url, timeout=wait)
        ws.call("Page.enable")
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": width, "height": height, "deviceScaleFactor": scale,
                 "mobile": False})
        ws.call("Page.navigate", {"url": url})
        deadline = time.time() + wait
        if ready_js:
            while time.time() < deadline:
                try:
                    r = ws.call("Runtime.evaluate",
                                {"expression": f"!!({ready_js})", "returnByValue": True},
                                timeout=15)
                    if r.get("result", {}).get("value") is True:
                        break
                except RuntimeError:
                    pass
                time.sleep(0.4)
            else:
                log("  ! 렌더 완료 신호를 못 받아 현재 화면을 그대로 찍습니다")
        time.sleep(0.6)                      # 마지막 프레임이 합성될 여유
        res = ws.call("Page.captureScreenshot", {"format": "png",
                                                 "captureBeyondViewport": False},
                      timeout=60)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(res["data"]))
        return out
    finally:
        if ws:
            ws.close()
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _wait_debugger(port: int, timeout: float = 25.0) -> str:
    """**페이지 타겟**의 웹소켓 주소. /json/version 이 주는 브라우저 수준 주소로는
    Page.* / Runtime.* 을 쓸 수 없다 ('Page.enable' wasn't found)."""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list",
                                        timeout=2) as r:
                for t in json.loads(r.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    raise TimeoutError("Chrome 페이지 타겟을 찾지 못했습니다")
