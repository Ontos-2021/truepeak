import numpy as np
from scipy.signal import lfilter

LUFS_OFFSET = -0.691
ABS_GATE_LUFS = -70.0
REL_GATE_LU = 10.0
LRA_REL_GATE_LU = 20.0


def k_weight_coefficients(fs):
    f0 = 1681.974450955533
    gain_db = 3.999843853973347
    q = 0.7071752369554196
    k = np.tan(np.pi * f0 / fs)
    vh = 10.0 ** (gain_db / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    shelf_b = np.array([
        (vh + vb * k / q + k * k) / a0,
        2.0 * (k * k - vh) / a0,
        (vh - vb * k / q + k * k) / a0,
    ])
    shelf_a = np.array([
        1.0,
        2.0 * (k * k - 1.0) / a0,
        (1.0 - k / q + k * k) / a0,
    ])

    f0 = 38.13547087602444
    q = 0.5003270373238773
    k = np.tan(np.pi * f0 / fs)
    denom = 1.0 + k / q + k * k
    hp_b = np.array([1.0, -2.0, 1.0])
    hp_a = np.array([
        1.0,
        2.0 * (k * k - 1.0) / denom,
        (1.0 - k / q + k * k) / denom,
    ])
    return shelf_b, shelf_a, hp_b, hp_a


class KWeight:
    def __init__(self, fs, n_channels):
        self.b1, self.a1, self.b2, self.a2 = k_weight_coefficients(fs)
        self.zi1 = np.zeros((2, n_channels))
        self.zi2 = np.zeros((2, n_channels))

    def process(self, block):
        y, self.zi1 = lfilter(self.b1, self.a1, block, axis=0, zi=self.zi1)
        y, self.zi2 = lfilter(self.b2, self.a2, y, axis=0, zi=self.zi2)
        return y


def lufs_from_mean_square(z):
    with np.errstate(divide="ignore", invalid="ignore"):
        return LUFS_OFFSET + 10.0 * np.log10(z)


def sliding_mean(z, width):
    if z.size < width:
        return np.empty(0, dtype=np.float64)
    cs = np.concatenate(([0.0], np.cumsum(z)))
    return (cs[width:] - cs[:-width]) / width


def integrated_loudness(block_mean_squares):
    z = np.asarray(block_mean_squares, dtype=np.float64)
    z = z[np.isfinite(z) & (z > 0.0)]
    if z.size == 0:
        return None
    abs_keep = z > 10.0 ** ((ABS_GATE_LUFS - LUFS_OFFSET) / 10.0)
    if not abs_keep.any():
        return None
    za = z[abs_keep]
    rel_threshold = lufs_from_mean_square(za.mean()) - REL_GATE_LU
    keep = za[lufs_from_mean_square(za) > rel_threshold]
    if keep.size == 0:
        keep = za
    return float(lufs_from_mean_square(keep.mean()))


def loudness_range(short_term_lufs):
    levels = np.asarray(short_term_lufs, dtype=np.float64)
    levels = levels[np.isfinite(levels)]
    if levels.size < 2:
        return None
    abs_keep = levels > ABS_GATE_LUFS
    if abs_keep.sum() < 2:
        return None
    gated = levels[abs_keep]
    power = 10.0 ** ((gated - LUFS_OFFSET) / 10.0)
    rel_threshold = float(lufs_from_mean_square(power.mean()) - LRA_REL_GATE_LU)
    keep = gated[gated > rel_threshold]
    if keep.size < 2:
        return None
    return float(np.percentile(keep, 95) - np.percentile(keep, 10))


class LoudnessAccumulator:
    def __init__(self, fs, n_channels, channel_weights, hop_seconds=0.1):
        self.fs = fs
        self.hop_frames = max(1, int(round(fs * hop_seconds)))
        self.kweight = KWeight(fs, n_channels)
        self.weights = np.asarray(channel_weights, dtype=np.float64)[:n_channels]
        self._tail = np.empty(0, dtype=np.float64)
        self._energies = []

    def process(self, block):
        y = self.kweight.process(block)
        weighted = y * y * self.weights[None, :]
        mono_energy = weighted.sum(axis=1)
        if self._tail.size:
            mono_energy = np.concatenate((self._tail, mono_energy))
        n_hops = mono_energy.size // self.hop_frames
        if n_hops:
            usable = n_hops * self.hop_frames
            framed = mono_energy[:usable].reshape(n_hops, self.hop_frames)
            self._energies.append(framed.sum(axis=1))
            self._tail = mono_energy[usable:].copy()
        else:
            self._tail = mono_energy

    def finish(self):
        hop_seconds = self.hop_frames / self.fs
        if self._energies:
            energies = np.concatenate(self._energies)
        else:
            energies = np.empty(0, dtype=np.float64)
        empty = energies.size == 0 or energies.max() <= 0.0
        if empty:
            return {
                "integrated_lufs": None,
                "momentary_max_lufs": None,
                "short_term_max_lufs": None,
                "lra_lu": None,
                "t_momentary": [],
                "momentary": [],
                "t_short_term": [],
                "short_term": [],
            }
        z = energies / self.hop_frames
        z_momentary = sliding_mean(z, 4)
        z_short_term = sliding_mean(z, 30)
        momentary = lufs_from_mean_square(z_momentary)
        short_term = lufs_from_mean_square(z_short_term)
        t_momentary = (np.arange(z_momentary.size) + 2.0) * hop_seconds
        t_short_term = (np.arange(z_short_term.size) + 15.0) * hop_seconds
        integrated = integrated_loudness(z_momentary)
        lra = loudness_range(short_term)
        finite_m = momentary[np.isfinite(momentary)]
        finite_s = short_term[np.isfinite(short_term)]
        return {
            "integrated_lufs": integrated,
            "momentary_max_lufs": float(finite_m.max()) if finite_m.size else None,
            "short_term_max_lufs": float(finite_s.max()) if finite_s.size else None,
            "lra_lu": lra,
            "t_momentary": t_momentary.tolist(),
            "momentary": momentary.tolist(),
            "t_short_term": t_short_term.tolist(),
            "short_term": short_term.tolist(),
        }
