/* pcmplay: plays 44.1 kHz stereo S16_LE from stdin on the speaker's PCM device.
 * Bridge for: shairport-sync -o stdout | pcmplay [true_output_rate]
 *
 * The Cube's codec clock runs at about 48045 Hz even when ALSA is configured for 44100
 * (measured from hw_ptr and tstamp). So the device is opened at 44100, as the driver reports,
 * and the audio is resampled here to the true rate, using linear interpolation in integer maths.
 *
 * The device is opened only while audio is arriving and closed after 2 s of silence on stdin,
 * so Bluetooth and the stock audio services can use it the rest of the time. If it is busy,
 * incoming audio is discarded until it becomes free.
 *
 * Buffer 32768 frames, starts once 16384 are queued. Logs level and underruns every 10 s of input.
 */
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sound/asound.h>

#define INPUT_RATE 44100
#define DEFAULT_OUTPUT_RATE 48045
#define MAX_IN_FRAMES 1024
#define MAX_OUT_FRAMES 1400
#define IDLE_CLOSE_MS 2000

static void mask(struct snd_pcm_hw_params *p, int n, unsigned b) {
    struct snd_mask *m = &p->masks[n - SNDRV_PCM_HW_PARAM_FIRST_MASK];
    memset(m, 0, sizeof *m);
    m->bits[b >> 5] |= 1u << (b & 31);
}

static void itv(struct snd_pcm_hw_params *p, int n, unsigned v) {
    struct snd_interval *i = &p->intervals[n - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL];
    i->min = i->max = v;
    i->integer = 1;
    i->openmin = i->openmax = i->empty = 0;
}

static int f = -1;
static long under;

static int pcm_open(void) {
    int fd = open("/dev/snd/pcmC0D0p", O_WRONLY);
    if (fd < 0) return -1;

    struct snd_pcm_hw_params p;
    memset(&p, 0, sizeof p);
    memset(p.masks, 0xff, sizeof p.masks);
    for (int i = 0; i <= SNDRV_PCM_HW_PARAM_LAST_INTERVAL - SNDRV_PCM_HW_PARAM_FIRST_INTERVAL; i++) {
        p.intervals[i].min = 0;
        p.intervals[i].max = ~0u;
    }
    p.rmask = ~0u;
    p.info = ~0u;
    mask(&p, SNDRV_PCM_HW_PARAM_ACCESS, SNDRV_PCM_ACCESS_RW_INTERLEAVED);
    mask(&p, SNDRV_PCM_HW_PARAM_FORMAT, SNDRV_PCM_FORMAT_S16_LE);
    mask(&p, SNDRV_PCM_HW_PARAM_SUBFORMAT, SNDRV_PCM_SUBFORMAT_STD);
    itv(&p, SNDRV_PCM_HW_PARAM_SAMPLE_BITS, 16);
    itv(&p, SNDRV_PCM_HW_PARAM_FRAME_BITS, 32);
    itv(&p, SNDRV_PCM_HW_PARAM_CHANNELS, 2);
    itv(&p, SNDRV_PCM_HW_PARAM_RATE, 44100);
    itv(&p, SNDRV_PCM_HW_PARAM_PERIOD_SIZE, 2048);
    itv(&p, SNDRV_PCM_HW_PARAM_PERIODS, 16);
    if (ioctl(fd, SNDRV_PCM_IOCTL_HW_PARAMS, &p)) {
        fprintf(stderr, "hw_params: %s\n", strerror(errno));
        close(fd);
        return -1;
    }

    struct snd_pcm_sw_params sw;
    memset(&sw, 0, sizeof sw);
    sw.period_step = 1;
    sw.avail_min = 2048;
    sw.start_threshold = 16384;
    sw.stop_threshold = 32768;
    if (ioctl(fd, SNDRV_PCM_IOCTL_SW_PARAMS, &sw)) fprintf(stderr, "sw_params: %s\n", strerror(errno));
    if (ioctl(fd, SNDRV_PCM_IOCTL_PREPARE)) {
        fprintf(stderr, "prepare: %s\n", strerror(errno));
        close(fd);
        return -1;
    }
    return fd;
}

static int write_frames(const short *out, size_t frames) {
    while (frames) {
        struct snd_xferi x = { .result = 0, .buf = (void *)out, .frames = frames };
        if (ioctl(f, SNDRV_PCM_IOCTL_WRITEI_FRAMES, &x)) {
            if (errno == EPIPE) {
                under++;
                ioctl(f, SNDRV_PCM_IOCTL_PREPARE);
                continue;
            }
            fprintf(stderr, "write: %s\n", strerror(errno));
            return -1;
        }
        out += x.result * 2;
        frames -= x.result;
    }
    return 0;
}

int main(int argc, char **argv) {
    unsigned out_rate = argc > 1 ? (unsigned)atoi(argv[1]) : DEFAULT_OUTPUT_RATE;
    uint32_t step = (uint32_t)(((uint64_t)INPUT_RATE << 16) / out_rate);
    fprintf(stderr, "resampling %d -> %u Hz, device opened on demand\n", INPUT_RATE, out_rate);

    static short in[MAX_IN_FRAMES * 2], out[MAX_OUT_FRAMES * 2];
    size_t have = 0;
    long total = 0, since = 0;
    int peak = 0, busy_logged = 0;
    int32_t prev_l = 0, prev_r = 0;
    uint32_t phase = 0;

    for (;;) {
        struct pollfd pfd = { .fd = 0, .events = POLLIN };
        int ready = poll(&pfd, 1, f >= 0 ? IDLE_CLOSE_MS : -1);
        if (ready == 0) {  /* no audio for a while: release the device */
            ioctl(f, SNDRV_PCM_IOCTL_DRAIN);
            close(f);
            f = -1;
            have = 0;
            phase = 0;
            prev_l = prev_r = 0;
            fprintf(stderr, "idle, device released, xruns=%ld\n", under);
            continue;
        }
        if (ready < 0) { if (errno == EINTR) continue; break; }

        ssize_t n = read(0, (char *)in + have, sizeof in - have);
        if (n <= 0) break;
        have += n;
        size_t frames = have / 4, produced = 0;

        if (f < 0) {
            f = pcm_open();
            if (f < 0) {
                if (!busy_logged) { fprintf(stderr, "device busy, discarding audio\n"); busy_logged = 1; }
                have -= frames * 4;
                if (have) memmove(in, (char *)in + frames * 4, have);
                continue;
            }
            busy_logged = 0;
            fprintf(stderr, "device opened\n");
        }

        for (size_t i = 0; i < frames; i++) {
            int32_t l = in[2 * i], r = in[2 * i + 1];
            int a = l < 0 ? -l : l, b = r < 0 ? -r : r;
            if (a > peak) peak = a;
            if (b > peak) peak = b;
            while (phase < 65536) {
                out[2 * produced] = (short)(prev_l + (((l - prev_l) * (int32_t)(phase >> 1)) >> 15));
                out[2 * produced + 1] = (short)(prev_r + (((r - prev_r) * (int32_t)(phase >> 1)) >> 15));
                produced++;
                phase += step;
            }
            phase -= 65536;
            prev_l = l;
            prev_r = r;
        }

        if (write_frames(out, produced)) return 5;

        total += frames;
        since += frames;
        if (since >= 441000) {
            fprintf(stderr, "frames=%ld peak=%d xruns=%ld\n", total, peak, under);
            since = 0;
            peak = 0;
        }
        size_t used = frames * 4;
        have -= used;
        if (have) memmove(in, (char *)in + used, have);
    }
    if (f >= 0) {
        ioctl(f, SNDRV_PCM_IOCTL_DRAIN);
        close(f);
    }
    fprintf(stderr, "underruns: %ld\n", under);
    return 0;
}
