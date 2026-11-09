# Debug helpers

None of these are needed to build the firmware. They are for poking at a speaker, or testing changes before flashing.

Set the speaker's address first:

```sh
export TIVOLI_HOST=<speaker-ip>
```

| File | What it does |
|---|---|
| `t.py` | Runs one command on the speaker over telnet and prints the output |
| `raop_test.py` | A minimal AirPlay 1 sender that streams test tones to a receiver |
| `deploy.py` | Copies a build to a USB stick in the speaker and starts AirPlay from there, without flashing |
| `recv.c` | Tiny file receiver for the speaker, used by `deploy.py` |

## t.py

```sh
python3 t.py 'cat /proc/uptime'
python3 t.py -t 30 'logcat -d | grep -i airplay'
```

`-t` is how many seconds to wait for output (default 15).

The stock telnet service is not a real shell. It runs each line separately and has no terminal:

- `cd` and variables do not carry over between commands.
- Lines are limited to about 1 KB.
- There is no `head`, `tail`, `nc` or `wget`. Filter with `grep` on the speaker instead.
- Keep connections few and short. Too many can hang the service until the next reboot.
- To start something in the background, wrap it as `{ command & }`.

## raop_test.py

```sh
python3 raop_test.py <host> <port> [seconds]
python3 raop_test.py "$TIVOLI_HOST" 5000 7
```

Sends 1000 Hz on the left channel and 1500 Hz on the right, unencrypted. **This makes sound on a real speaker.** The level defaults to a quiet 600 of 32767; change it with `RAOP_AMP=<level>`.

It can also test a build on your PC under QEMU, with no speaker:

```sh
qemu-mipsel -cpu 24Kc build/dl/shairport-sync/shairport-sync -a Test -p 7050 -o stdout > out.pcm &
python3 tools/dev/raop_test.py 127.0.0.1 7050 7
```

## deploy.py

Tests a build on a speaker running from a USB stick, without touching flash. A reboot undoes everything except the files on the stick. It makes no sound until something streams to it.

Needs a FAT stick mounted on the speaker at `/media/usb`, with `sps.conf` on it containing:

```
general = { interface = "wlan0"; };
```

Do not leave a file named `lsimage` on that stick, or it may trigger a flash at boot.

Build `recv` first, then run it from the repo root:

```sh
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/p" muslcc/x86_64:mipsel-linux-muslsf \
    gcc -static -no-pie -s -Os -march=mips32r2 -msoft-float /p/tools/dev/recv.c -o /p/build/recv
python3 tools/dev/deploy.py build
```

It stops the stock `spotify` and `mdnsd`, adds the multicast route, and starts the receiver. Logs go to `/data/local/tmp/` on the speaker.

## recv.c

`recv <port> <outfile>` accepts one TCP connection and writes what it receives to a file. It exists because the stock firmware has no `nc`, `wget` or `scp`. `deploy.py` first sends it over telnet in small chunks, then uses it for the larger files.
