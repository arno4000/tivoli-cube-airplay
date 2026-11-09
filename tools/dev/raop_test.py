#!/usr/bin/env python3
"""Minimal AirPlay 1 (RAOP) sender for testing shairport-sync.

Sends unencrypted, uncompressed-ALAC stereo: 1000 Hz left, 1500 Hz right.
usage: raop_test.py HOST PORT [SECONDS]
"""
import base64
import math
import os
import re
import socket
import struct
import sys
import threading
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 7.0
FRAMES = 352
RATE = 44100
LATENCY = 11025
AMP = int(os.environ.get("RAOP_AMP", "600"))  # quiet by default; the audible beep test used 1200
NTP_OFFSET = 2208988800


def ntp_now():
    t = time.time() + NTP_OFFSET
    return (int(t) << 32) | int((t - int(t)) * (1 << 32))


rtsp = socket.create_connection((HOST, PORT), timeout=15)
cseq = 0
SESSION = None
URL = f"rtsp://{HOST}/1"


def request(method, url=URL, headers=None, body=b""):
    global cseq
    cseq += 1
    lines = [f"{method} {url} RTSP/1.0", f"CSeq: {cseq}", "User-Agent: raop-test/1.0",
             "Client-Instance: 0123456789ABCDEF", "DACP-ID: 0123456789ABCDEF"]
    if SESSION:
        lines.append(f"Session: {SESSION}")
    for k, v in (headers or {}).items():
        lines.append(f"{k}: {v}")
    if body:
        lines.append(f"Content-Length: {len(body)}")
    rtsp.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = rtsp.recv(65536)
        if not chunk:
            raise SystemExit(f"{method}: connection closed; got {data!r}")
        data += chunk
    head, rest = data.split(b"\r\n\r\n", 1)
    text = head.decode("latin1")
    status = text.split("\r\n")[0]
    res = dict(re.findall(r"^([\w-]+):\s*(.*?)\r?$", text, re.M))
    need = int(res.get("Content-Length", 0))
    while len(rest) < need:
        rest += rtsp.recv(65536)
    print(f"{method}: {status}")
    if " 200 " not in status + " ":
        raise SystemExit(f"{method} failed: {text}")
    return res


challenge = base64.b64encode(os.urandom(16)).rstrip(b"=").decode()
r = request("OPTIONS", "*", {"Apple-Challenge": challenge})
print("  Apple-Response:", "present, %d chars" % len(r["Apple-Response"]) if "Apple-Response" in r else "MISSING")

sdp = (f"v=0\r\no=iTunes 1 0 IN IP4 {HOST}\r\ns=iTunes\r\nc=IN IP4 {HOST}\r\nt=0 0\r\n"
       "m=audio 0 RTP/AVP 96\r\na=rtpmap:96 AppleLossless\r\n"
       f"a=fmtp:96 {FRAMES} 0 16 40 10 14 2 255 0 0 {RATE}\r\n").encode()
request("ANNOUNCE", headers={"Content-Type": "application/sdp"}, body=sdp)

control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
control.bind(("", 0))
timing = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
timing.bind(("", 0))
audio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

r = request("SETUP", headers={"Transport":
            "RTP/AVP/UDP;unicast;interleaved=0-1;mode=record;"
            f"control_port={control.getsockname()[1]};timing_port={timing.getsockname()[1]}"})
SESSION = r["Session"].split(";")[0]
transport = r["Transport"]
server_port = int(re.search(r"server_port=(\d+)", transport).group(1))
server_control = int(re.search(r"control_port=(\d+)", transport).group(1))
print("  transport:", transport)

request("RECORD", headers={"Range": "npt=0-", "RTP-Info": "seq=0;rtptime=0"})
request("SET_PARAMETER", headers={"Content-Type": "text/parameters"}, body=b"volume: 0.000000\r\n")

running = True


def timing_loop():
    timing.settimeout(0.3)
    count = 0
    while running:
        try:
            pkt, addr = timing.recvfrom(128)
        except socket.timeout:
            continue
        if len(pkt) >= 32 and pkt[1] & 0x7f == 0x52:
            now = struct.pack(">Q", ntp_now())
            reply = bytes([0x80, 0xd3]) + pkt[2:4] + b"\0\0\0\0" + pkt[24:32] + now + now
            timing.sendto(reply, addr)
            count += 1
    print("  timing replies sent:", count)


threading.Thread(target=timing_loop, daemon=True).start()


def alac_frame(start):
    samples = 0
    for i in range(FRAMES):
        n = start + i
        left = int(AMP * math.sin(2 * math.pi * 1000.0 * n / RATE)) & 0xffff
        right = int(AMP * math.sin(2 * math.pi * 1500.0 * n / RATE)) & 0xffff
        samples = (samples << 32) | (left << 16) | right
    header = (1 << 20) | 1  # 3 bits channels-1, 4+12 unused, hassize=0, 2 unused, not-compressed=1
    bits = 23 + FRAMES * 32
    pad = (8 - bits % 8) % 8
    return (((header << (FRAMES * 32)) | samples) << pad).to_bytes((bits + pad) // 8, "big")


def send_sync(first, ts):
    b0 = 0x90 if first else 0x80
    control.sendto(struct.pack(">BBHIQI", b0, 0xd4, 7, (ts - LATENCY) & 0xffffffff, ntp_now(), ts & 0xffffffff),
                   (HOST, server_control))


ssrc = 0x12345678
seq = 0
ts = 0
t0 = time.time()
sent = 0
send_sync(True, ts)
last_sync = time.time()
while sent * FRAMES / RATE < SECONDS:
    target = t0 + sent * FRAMES / RATE
    delay = target - time.time()
    if delay > 0:
        time.sleep(delay)
    if time.time() - last_sync >= 1.0:
        send_sync(False, ts)
        last_sync = time.time()
    marker = 0xe0 if sent == 0 else 0x60
    pkt = struct.pack(">BBHII", 0x80, marker, seq & 0xffff, ts & 0xffffffff, ssrc) + alac_frame(ts)
    audio.sendto(pkt, (HOST, server_port))
    seq += 1
    ts += FRAMES
    sent += 1
print("packets sent:", sent, "frames:", ts)
time.sleep(3.5)
running = False
try:
    request("TEARDOWN")
except (SystemExit, OSError) as e:
    print("TEARDOWN:", e)
time.sleep(0.5)
rtsp.close()
