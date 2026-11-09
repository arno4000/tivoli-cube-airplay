#!/usr/bin/env python3
"""Run a command on the speaker via raw telnet. usage: t.py [-t secs] 'cmd'"""
import socket, sys, time, select, uuid

import os
HOST, PORT = os.environ["TIVOLI_HOST"], 23
args = sys.argv[1:]
timeout = 15.0
if args and args[0] == "-t":
    timeout = float(args[1]); args = args[2:]
cmd = " ".join(args)
s = socket.create_connection((HOST, PORT), timeout=10)

def strip_iac(b):
    out = bytearray(); i = 0
    while i < len(b):
        if b[i] == 255 and i + 1 < len(b):
            if b[i+1] in (251, 252, 253, 254) and i + 2 < len(b):
                # refuse all options
                s.sendall(bytes([255, 254 if b[i+1] in (251,252) else 252, b[i+2]]))
                i += 3; continue
            i += 2; continue
        out.append(b[i]); i += 1
    return bytes(out)

def read(dur, until=None):
    buf = b""; end = time.time() + dur
    while time.time() < end:
        r, _, _ = select.select([s], [], [], 0.2)
        if r:
            d = s.recv(65536)
            if not d: break
            buf += strip_iac(d)
            if until and until in buf: break
    return buf

read(1.0)
mark = uuid.uuid4().hex[:8]
s.sendall((cmd + f"; echo {mark}E''ND;\n").encode())
out = read(timeout, (mark + "END").encode())
sys.stdout.write(out.decode("utf-8", "replace").replace("\r", ""))
s.close()
