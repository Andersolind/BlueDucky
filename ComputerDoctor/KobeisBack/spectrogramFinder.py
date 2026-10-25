"""
Synthesize complex baseband (IQ) whose spectrogram spells text, formatted
for hackrf_transfer (interleaved signed 8-bit, .cs8). The text band is
offset away from DC so it clears the HackRF's LO-leakage spike at the carrier.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.signal import spectrogram
import matplotlib.pyplot as plt
import glob, matplotlib

SR   = 2_000_000     # HackRF baseband sample rate (>= 2 Msps). Set -s to match.
DUR  = 1.0           # seconds of transmission
ROWS = 160           # vertical resolution -> number of tones
F_LO = 60_000        # text band, as OFFSET from the carrier (Hz). Clears DC.
F_HI = 260_000       # keep within +/- SR/2 (here +/-1 MHz)

def render_text(text, rows=ROWS):
    fp = glob.glob(matplotlib.get_data_path() + "/fonts/ttf/DejaVuSans-Bold.ttf")[0]
    font = ImageFont.truetype(fp, int(rows * 0.7))
    w = ImageDraw.Draw(Image.new("L", (10, 10))).textbbox((0, 0), text, font=font)[2]
    img = Image.new("L", (w + rows, rows), 0)
    ImageDraw.Draw(img).text((rows // 2, rows * 0.1), text, fill=255, font=font)
    return np.flipud(np.asarray(img, float) / 255.0)   # up = higher freq

def synth_iq(mask):
    rows, cols = mask.shape
    n = int(SR * DUR)
    t = np.arange(n) / SR
    freqs = np.linspace(F_LO, F_HI, rows)              # linear reads clean at RF
    iq = np.zeros(n, dtype=np.complex128)
    for r in range(rows):
        if not mask[r].any():
            continue
        env = np.interp(np.linspace(0, cols, n), np.arange(cols), mask[r])
        phi = np.random.uniform(0, 2 * np.pi)
        iq += env * np.exp(1j * (2 * np.pi * freqs[r] * t + phi))
    iq /= np.max(np.abs(iq)) + 1e-9                     # normalize magnitude
    return iq * 0.9

def save_cs8(iq, path):
    """hackrf_transfer native format: interleaved I,Q as signed 8-bit."""
    inter = np.empty(iq.size * 2, dtype=np.int8)
    inter[0::2] = np.clip(np.real(iq) * 127, -127, 127).astype(np.int8)
    inter[1::2] = np.clip(np.imag(iq) * 127, -127, 127).astype(np.int8)
    inter.tofile(path)

def plot_iq_spectrogram(iq, path, title):
    from scipy.signal import decimate
    d = decimate(iq, 3, ftype="fir")          # content is within +/-260 kHz
    fs = SR / 3
    f, tt, Sxx = spectrogram(d, fs, nperseg=1024, noverlap=512,
                             return_onesided=False)
    f = np.fft.fftshift(f); Sxx = np.fft.fftshift(Sxx, axes=0)
    plt.figure(figsize=(11, 4.5))
    plt.imshow(10 * np.log10(Sxx + 1e-12), origin="lower", aspect="auto",
               extent=[tt[0], tt[-1], f[0] / 1e3, f[-1] / 1e3], cmap="magma")
    plt.ylim(-400, 400)
    plt.ylabel("Offset from carrier (kHz)"); plt.xlabel("Time (s)"); plt.title(title)
    plt.colorbar(label="Power (dB)"); plt.tight_layout(); plt.savefig(path, dpi=130)

if __name__ == "__main__":
    TEXT = "CQ DE VA3"                # e.g. a callsign beacon
    iq = synth_iq(render_text(TEXT))
    save_cs8(iq, "/home/claude/caption.cs8")
    plot_iq_spectrogram(iq, "/home/claude/iq_spectrogram.png",
                        f'Complex baseband spectrogram of "{TEXT}"')
    print(f"wrote caption.cs8: {iq.size} samples, {iq.size*2} bytes")