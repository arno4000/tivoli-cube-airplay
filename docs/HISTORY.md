# How this project came about

The speaker worked with Spotify Connect until, one day, it didn't. It still appeared in the Spotify app, but played nothing except a faint hum. This is what happened next.

## 1. Looking for the bug

The Cube turned out to be easy to get into: it ships with passwordless root telnet. Inside is a Libre Wireless LS6 module running a cut-down Android 4.2 userland on a MIPS chip.

The logs showed Spotify logging in fine, then failing every track with `Spotify Embedded error 1001`, within about a tenth of a second and before any audio was fetched.

The first suspects were all ruled out:

- Bluetooth worked, so the amp and speaker were fine.
- DNS for Spotify's servers resolved correctly.
- Reflashing Tivoli's own firmware changed nothing.
- A factory reset did not bring it back.

The answer came from the Spotify app, which then labelled the speaker **"No longer works with Spotify"**. Spotify had retired the 2017-era SDK inside the firmware. Nothing on the speaker was broken.

## 2. Trying to bring Spotify back

The obvious replacement was [librespot](https://github.com/librespot-org/librespot), an open source Spotify Connect client.

Before porting it, a small test ran on the real hardware:

| Test | Result |
|---|---|
| Our own static MIPS program runs | Yes |
| Direct sound output | Yes, audible |
| Vorbis decode, fixed-point | 5.9% of real time |
| Vorbis decode, soft-float | 83.4% of real time |

librespot then compiled for the chip, ran on the speaker, and logged in. Then every track failed with `error audio key 0 1`.

The same error appeared with go-librespot, and with a normal librespot package on a desktop PC. It is a Spotify-side refusal, tracked in [librespot #1649](https://github.com/librespot-org/librespot/issues/1649), with no known fix. The Spotify route ended there.

## 3. AirPlay instead

The firmware contains Apple's official AirPlay receiver, but it never worked on the tested speaker. It appears to depend on Apple's MFi authentication, which is the likely reason it failed.

[shairport-sync](https://github.com/mikebrady/shairport-sync) needs none of that. It was cross-compiled as a static binary of under 800 KB, first tested under QEMU with a small hand-written AirPlay sender, which got back exactly the test tones it sent.

On the real speaker, two problems showed up.

**Nobody could find it.** The speaker's multicast traffic left through its setup-hotspot interface instead of Wi-Fi. A multicast route and one config line fixed that. This was also why librespot's announcements had been flaky.

**It was choppy.** The network was clean and the CPU almost idle, yet the audio buffer kept running dry at a steady rate. Measuring the audio clock, by playing silence and timing the hardware pointer, showed the codec really runs at about **48045 Hz while the driver claims 44100**. So everything played about 9% fast. Adding a small integer resampler to `pcmplay` fixed the dropouts and the pitch.

## 4. Making it permanent

The root filesystem lives in RAM, so anything started by hand vanishes at reboot. The fix was a rebuilt firmware image.

Unpacking Tivoli's image showed how it fits together: a `SPLT` container, a gzip kernel image, and an LZMA root filesystem inside a fixed-size slot in the kernel. The new filesystem had to fit that slot exactly, which meant using the original compression settings and dropping a couple of unused files.

Before flashing, a read-only backup of the flash revealed that the updater is a separate image from the main firmware, and that it validates images with CRC checks, not signatures.

The custom image was flashed with the speaker's normal USB update method, booted first time, and appeared as an AirPlay device with no help.

## What's left

- AirPlay 1 only, on a trusted home network.
- Testing has been limited to one speaker.
- It once dropped off the network during development for reasons that were never found.
