#!/usr/bin/env python3
"""Builds a custom lsimage: Spotify disabled, AirPlay 1 (shairport-sync + pcmplay) started by init.

usage: build_image.py STOCK_LSIMAGE SHAIRPORT PCMPLAY START_SCRIPT OUTPUT

Everything else in the image is preserved byte for byte. Refuses to write if anything does not fit.
Does not flash anything.
"""
import gzip
import hashlib
import lzma
import struct
import sys
import zlib

stock, shairport, pcmplay, start_script, output = sys.argv[1:6]

UIMAGE = 0x4c
SECTION_A_LEN = 0xd257b5
LZMA_OFF = 0x6D1550
DICT = 1048576

INIT_SNIPPET = b"""
# Custom firmware: AirPlay 1 receiver (shairport-sync), see NOTES.md
service airplay /system/bin/sh /system/bin/start-airplay
    class main
    user root
"""
SPOTIFY_STUB = b"#!/system/bin/sh\n# Spotify Connect was retired for this device; disabled by custom firmware.\nexit 0\n"
SPS_CONF = b'general = { interface = "wlan0"; };\n'


def parse_cpio(blob):
    entries, p = [], 0
    while blob[p:p + 6] == b"070701":
        f = [int(blob[p + 6 + 8 * i:p + 14 + 8 * i], 16) for i in range(13)]
        nsize, fsize = f[11], f[6]
        name = blob[p + 110:p + 110 + nsize - 1]
        dpos = (p + 110 + nsize + 3) & ~3
        data = blob[dpos:dpos + fsize]
        if name == b"TRAILER!!!":
            return entries, f
        entries.append((name, f, data))
        p = (dpos + fsize + 3) & ~3
    raise SystemExit("cpio trailer not found")


def pack_cpio(entries, trailer):
    out = bytearray()

    def add(name, f, data):
        f = list(f)
        f[6], f[11] = len(data), len(name) + 1
        out.extend(b"070701" + b"".join(b"%08X" % x for x in f))
        out.extend(name + b"\0")
        while len(out) % 4:
            out.append(0)
        out.extend(data)
        while len(out) % 4:
            out.append(0)

    for name, f, data in entries:
        add(name, f, data)
    add(b"TRAILER!!!", trailer, b"")
    while len(out) % 512:
        out.append(0)
    return bytes(out)


def decode(image):
    """Returns (kernel, lzma_len, cpio) and verifies every checksum along the way."""
    if image[:4] != b"SPLT" or struct.unpack("<I", image[4:8])[0] != zlib.crc32(image[0x30:]):
        raise SystemExit("SPLT checksum mismatch")
    hdr = image[UIMAGE:UIMAGE + 64]
    if struct.unpack(">I", hdr[:4])[0] != 0x27051956:
        raise SystemExit("no uImage")
    hcrc = struct.unpack(">I", hdr[4:8])[0]
    if hcrc != zlib.crc32(hdr[:4] + b"\0\0\0\0" + hdr[8:]):
        raise SystemExit("uImage header CRC mismatch")
    size, dcrc = struct.unpack(">I", hdr[12:16])[0], struct.unpack(">I", hdr[24:28])[0]
    payload = image[UIMAGE + 64:UIMAGE + 64 + size]
    if zlib.crc32(payload) != dcrc:
        raise SystemExit("uImage data CRC mismatch")
    kernel = gzip.decompress(payload)
    d = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    cpio = d.decompress(kernel[LZMA_OFF:])
    return kernel, len(kernel) - LZMA_OFF - len(d.unused_data), cpio, size


image = open(stock, "rb").read()
kernel, old_lzma_len, cpio, old_gz_len = decode(image)
entries, trailer = parse_cpio(cpio)
stock_files = {n: d for n, f, d in entries}

size_field = struct.unpack("<I", kernel[LZMA_OFF + old_lzma_len + 1:LZMA_OFF + old_lzma_len + 5])[0]
if size_field != old_lzma_len:
    raise SystemExit(f"unexpected initramfs size field {size_field} != {old_lzma_len}")

template = next(f for n, f, d in entries if n == b"system/bin/telnet")
next_ino = max(f[0] for n, f, d in entries) + 1

# vTunerAppTest is a leftover test tool.
REMOVE = {b"system/lib/libspotify_embedded_shared.so", b"system/bin/vTunerAppTest",
          b"system/lib/libstagefright_soft_aacenc.so"}  # encoder only; the speaker only decodes
ALLOWED_REFERRERS = {b"system/bin/spotify"} | REMOVE
for victim in REMOVE:
    if victim not in stock_files:
        raise SystemExit(f"expected file missing: {victim}")
    base = victim.rsplit(b"/", 1)[1]
    for other, content in stock_files.items():
        if other not in ALLOWED_REFERRERS and base in content:
            raise SystemExit(f"{other} still references {base}; nothing written")

result = []
for name, f, data in entries:
    if name in REMOVE:
        continue
    if name == b"system/bin/spotify":
        data = SPOTIFY_STUB
    elif name == b"init.rc":
        anchor = b"service telnet /system/bin/telnet\n    class main\n    oneshot\n"
        if data.count(anchor) != 1:
            raise SystemExit("telnet service block not found once in init.rc")
        data = data.replace(anchor, anchor + INIT_SNIPPET)
    result.append((name, f, data))


def new_file(path, content, mode):
    global next_ino
    f = list(template)
    f[0], f[1] = next_ino, 0o100000 | mode
    next_ino += 1
    result.append((path, f, content))


new_file(b"system/bin/shairport-sync", open(shairport, "rb").read(), 0o755)
new_file(b"system/bin/pcmplay", open(pcmplay, "rb").read(), 0o755)
new_file(b"system/bin/start-airplay", open(start_script, "rb").read(), 0o755)
new_file(b"system/etc/sps.conf", SPS_CONF, 0o644)

new_cpio = pack_cpio(result, trailer)
filters = [{"id": lzma.FILTER_LZMA1, "preset": 9 | lzma.PRESET_EXTREME, "dict_size": DICT, "lc": 1, "lp": 2, "pb": 2,
            "nice_len": 273, "depth": 512, "mf": lzma.MF_BT4, "mode": lzma.MODE_NORMAL}]
new_lzma = lzma.compress(new_cpio, format=lzma.FORMAT_ALONE, filters=filters)
print(f"initramfs: {len(cpio)} -> {len(new_cpio)} bytes; LZMA {old_lzma_len} -> {len(new_lzma)} bytes "
      f"(slot {old_lzma_len}, spare {old_lzma_len - len(new_lzma)})")
if len(new_lzma) > old_lzma_len:
    raise SystemExit("new initramfs does not fit the kernel slot; nothing written")

new_kernel = bytearray(kernel)
new_kernel[LZMA_OFF:LZMA_OFF + old_lzma_len] = new_lzma + b"\0" * (old_lzma_len - len(new_lzma))
struct.pack_into("<I", new_kernel, LZMA_OFF + old_lzma_len + 1, len(new_lzma))

payload = gzip.compress(bytes(new_kernel), 9, mtime=0)
hdr = bytearray(image[UIMAGE:UIMAGE + 64])
struct.pack_into(">I", hdr, 12, len(payload))
struct.pack_into(">I", hdr, 24, zlib.crc32(payload))
struct.pack_into(">I", hdr, 4, 0)
struct.pack_into(">I", hdr, 4, zlib.crc32(bytes(hdr)))
uimage = bytes(hdr) + payload

# Keep every byte after the uImage (padding, web UI ZIP, FENV, MCU firmware) at its original offset.
old_end = UIMAGE + 64 + old_gz_len
new_end = UIMAGE + len(uimage)
padding_start = image[old_end:old_end + 16]
if padding_start != b"\xff" * 16:
    raise SystemExit("expected 0xFF padding after uImage")
ff_run = 0
while image[old_end + ff_run] == 0xff:
    ff_run += 1
print(f"uImage: {64 + old_gz_len} -> {len(uimage)} bytes; padding available {ff_run}")
if new_end > old_end + ff_run:
    raise SystemExit("new uImage overflows the padding; nothing written")

new_image = bytearray(image)
new_image[UIMAGE:old_end + ff_run] = uimage + b"\xff" * (old_end + ff_run - new_end)
if len(new_image) != len(image):
    raise SystemExit("length changed; nothing written")
struct.pack_into("<I", new_image, 4, zlib.crc32(bytes(new_image[0x30:])))
new_image = bytes(new_image)

# Verify by decoding what was just built.
k2, l2, cpio2, _ = decode(new_image)
if cpio2 != new_cpio or l2 != len(new_lzma):
    raise SystemExit("verification: decoded initramfs differs")
if struct.unpack("<I", k2[LZMA_OFF + old_lzma_len + 1:LZMA_OFF + old_lzma_len + 5])[0] != len(new_lzma):
    raise SystemExit("verification: size field wrong")
if k2[:LZMA_OFF] != kernel[:LZMA_OFF] or k2[LZMA_OFF + old_lzma_len + 5:] != kernel[LZMA_OFF + old_lzma_len + 5:]:
    raise SystemExit("verification: kernel changed outside the initramfs")
if new_image[old_end + ff_run:] != image[old_end + ff_run:]:
    raise SystemExit("verification: data after the padding changed")
files2, _ = parse_cpio(cpio2)
new_map = {n: d for n, f, d in files2}
added = sorted(set(new_map) - set(stock_files))
removed = sorted(set(stock_files) - set(new_map))
changed = sorted(n for n in new_map if n in stock_files and new_map[n] != stock_files[n])
print("added:", [x.decode() for x in added])
print("removed:", [x.decode() for x in removed])
print("changed:", [x.decode() for x in changed])
if len(added) != 4 or set(removed) != REMOVE or len(changed) != 2:
    raise SystemExit("verification: unexpected set of file changes")

open(output, "wb").write(new_image)
print(f"wrote {output}: {len(new_image)} bytes, md5 {hashlib.md5(new_image).hexdigest()}")
print("all checks passed")
