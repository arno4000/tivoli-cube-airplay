# Tivoli Cube custom firmware: AirPlay 1 after Spotify Connect

Spotify retired Spotify Connect on older speakers, including the Tivoli Audio Cube (the app shows "No longer works with Spotify"). This project rebuilds Tivoli's public firmware so the speaker runs [shairport-sync](https://github.com/mikebrady/shairport-sync), an open source AirPlay 1 receiver, and starts it at boot.

No firmware or vendor files are in this repository. `build.sh` downloads Tivoli's public image and patches it on your own machine.

> **Warning.** Flashing custom firmware can brick your speaker and may void your warranty. You do this at your own risk. This project has been tested on **one EU Cube** running firmware `p6128.131.1000`. It is not affiliated with Tivoli Audio, Libre Wireless, Spotify or Apple.

## What changes

| | |
|---|---|
| Added | `shairport-sync`, `pcmplay`, `start-airplay`, `sps.conf`, and an `airplay` service in `init.rc` |
| Disabled | `spotify` is replaced with a stub that exits immediately |
| Removed | The Spotify SDK library, a leftover test tool, and the AAC encoder plugin (needed to fit the image; playback only uses the decoder) |
| Unchanged | Kernel code, Bluetooth, web UI, telnet, factory settings, microcontroller firmware |

The speaker appears as an AirPlay device named `Cube`.

## Build

Needs Linux, Docker, git, curl and Python 3.

```sh
./build.sh
```

The result is `build/cfw/lsimage`. The script stops if the downloaded firmware is not the exact known build (MD5 `d6ce0540eaa4084e393878dda2233247`), because the patch relies on that build's layout. It also checks its own output: checksums, and that only the files listed above changed.

Source versions are pinned in `build.sh`.

## Flash

This is the speaker's normal update method.

1. Copy `build/cfw/lsimage` to a FAT-formatted USB stick, named exactly `lsimage`, with no other files on it.
2. Plug the stick into the micro-USB **SERVICE** port with an adapter.
3. Open `http://<speaker-ip>/index.asp`, go to Firmware Upgrade, select **USB**, leave **FACTORY RESET** unticked, and press Upgrade. Alternatively, power the speaker on, wait about 30 seconds, then plug in the stick.
4. Wait for it to finish, up to 10 minutes. Do not cut power or press buttons. The LED blinks while it works.
5. **Unplug the stick afterwards**, so it cannot flash again at the next boot.

To go back, flash the unmodified `lsimage` from Tivoli the same way.

## How it works

**Hardware.** Libre Wireless LS6 module: MT7620A (MIPS 24KEc, no FPU), 58 MB RAM, WM8904 codec, Android 4.2-style userland, Linux 3.10.

**Firmware layout.** `lsimage` is a `SPLT` container with a CRC32 of everything from offset 0x30. It holds a gzip uImage (kernel with LZMA initramfs), a web UI ZIP, default settings, and what looks like firmware for a separate microcontroller.

**Updates.** The updater (`bl2`) lives in a separate BSL image on flash, so an app update does not overwrite it. It checks the `SPLT` CRC and the uImage CRCs. No signature check was found.

**Two bugs had to be worked around:**

- **Audio clock.** The codec really runs at about 48045 Hz while ALSA reports 44100, which made audio play about 9% fast and run out of buffer. `pcmplay` resamples to the true rate.
- **Discovery.** Multicast left through the setup-hotspot interface (`p2p0`), so senders never found the speaker. `start-airplay` adds a multicast route via `wlan0`, and `sps.conf` makes it advertise the correct address.

**Why not stock AirPlay?** The firmware has Apple's official receiver, enabled with `setenv airplay 1`, but it relies on Apple's MFi authentication and did not work on the tested unit.

**Why not librespot?** It builds and runs on the speaker, but Spotify refused audio keys on the test account (`error audio key 0 1`), as tracked in [librespot #1649](https://github.com/librespot-org/librespot/issues/1649).

## Security notes

Use this on a trusted home network only.

- The stock firmware leaves root telnet open with no password on port 23. This project does not change that.
- Upstream marks the two small components used here (the Hammerton ALAC decoder and tinysvcmdns) as deprecated for security reasons. FFmpeg and Avahi would be too large for this device.
- AirPlay has no password by default.

## Known limits

- AirPlay 1 only.
- During testing the speaker once dropped off the network and needed a reboot; the cause is unknown.
- The kernel has no pseudo-terminal support, so telnet or SSH cannot give a full interactive terminal.

## Repository layout

| Path | Purpose |
|---|---|
| `build.sh` | One-command build |
| `tools/cfw/` | Image builder and boot script |
| `tools/airplay/` | shairport-sync build script and `pcmplay` |
| `tools/dev/` | Debug helpers: telnet runner, test sender, deploy to a USB stick |
| `docs/HISTORY.md` | How this project came about |

Helpers that talk to a speaker need `TIVOLI_HOST=<speaker-ip>` set.
