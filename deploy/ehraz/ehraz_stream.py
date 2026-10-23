"""Forced SSH command: carry opaque TLS bytes only to ehraz.io:443.

Runs as a dedicated unprivileged account. It accepts no destination arguments,
does not terminate TLS, and does not record the stream.
"""
import os
import select
import signal
import socket
import sys
import time


def main():
    if len(sys.argv) != 1:
        return 2
    signal.alarm(40)
    deadline = time.monotonic() + 35
    totals = [0, 0]
    with socket.create_connection(("ehraz.io", 443), timeout=5) as remote:
        remote.settimeout(5)
        while time.monotonic() < deadline:
            readable, _, _ = select.select([0, remote], [], [], 1)
            for source in readable:
                if source == 0:
                    block = os.read(0, 65536)
                    direction = 0
                else:
                    block = remote.recv(65536)
                    direction = 1
                if not block:
                    return 0
                totals[direction] += len(block)
                if totals[direction] > 2 * 1024 * 1024:
                    return 3
                if direction == 0:
                    remote.sendall(block)
                else:
                    view = memoryview(block)
                    while view:
                        view = view[os.write(1, view):]
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, TimeoutError):
        raise SystemExit(1)
