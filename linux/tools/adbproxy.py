#!/usr/bin/env python3
"""Minimal HTTP/CONNECT proxy for adb reverse.

Listens on 127.0.0.1:3128. The phone reaches it via
`adb reverse tcp:3128 tcp:3128`. Needs no privileges.
"""
import select
import socket
import threading
from urllib.parse import urlsplit

PORT = 3128


def pipe(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 120)
            if not r:
                return
            for s in r:
                data = s.recv(65536)
                if not data:
                    return
                (b if s is a else a).sendall(data)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def handle(c):
    try:
        req = b""
        while b"\r\n\r\n" not in req:
            d = c.recv(4096)
            if not d:
                c.close()
                return
            req += d
            if len(req) > 65536:
                break
        head, _, rest = req.partition(b"\r\n\r\n")
        line = head.split(b"\r\n")[0].decode("latin1")
        method, target, _ = (line.split() + ["", "", ""])[:3]
        if method.upper() == "CONNECT":
            host, _, port = target.rpartition(":")
            up = socket.create_connection((host.strip("[]"), int(port or 443)), 15)
            c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            u = urlsplit(target)
            up = socket.create_connection((u.hostname, u.port or 80), 15)
            path = (u.path or "/") + (("?" + u.query) if u.query else "")
            headers = b"\r\n".join(head.split(b"\r\n")[1:])
            up.sendall(f"{method} {path} HTTP/1.1\r\n".encode("latin1") + headers + b"\r\n\r\n" + rest)
        pipe(c, up)
    except Exception:
        try:
            c.close()
        except Exception:
            pass


def main():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(64)
    print(f"proxy listening on 127.0.0.1:{PORT}", flush=True)
    while True:
        c, _ = s.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
