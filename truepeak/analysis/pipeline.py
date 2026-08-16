import numpy as np
from scipy.signal import welch

from .dsp import ArrayProvider, FileProvider, channel_weights
from .meter import LoudnessAccumulator
from .peaks import TruePeakScanner

CLIP_THRESHOLD = 0.999
HOP_SECONDS = 0.1
BLOCK_HOPS = 64
TRUE_PEAK_BLOCK_HOPS = 16
MAX_TIMELINE_POINTS = 2400
MAX_WAVEFORM_POINTS = 2048

THIRD_OCTAVE_CENTERS = np.array([
    25.0, 31.5, 40.0, 50.0, 63.0, 80.0, 100.0, 125.0, 160.0, 200.0,
    250.0, 315.0, 400.0, 500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0, 2000.0,
    2500.0, 3150.0, 4000.0, 5000.0, 6300.0, 8000.0, 10000.0, 12500.0,
    16000.0, 20000.0,
])

OFFSET_DB = -20.0


def _db(value):
    if value is None or value <= 0.0:
        return None
    return float(20.0 * np.log10(value))


class HopAggregator:
    def __init__(self, hop_frames):
        self.hop_frames = hop_frames
        self.tail = None

    def process(self, block, fn):
        if self.tail is not None:
            block = np.concatenate((self.tail, block), axis=0)
        n = (block.shape[0] // self.hop_frames) * self.hop_frames
        for start in range(0, n, self.hop_frames):
            fn(block[start:start + self.hop_frames])
        self.tail = block[n:].copy() if block.shape[0] > n else None

    def flush(self, fn):
        if self.tail is not None:
            fn(self.tail)
            self.tail = None


class LevelAccumulator:
    def __init__(self, n_channels):
        self.n_channels = n_channels
        self.frames = 0
        self.total = np.zeros(n_channels)
        self.sum_sq = np.zeros(n_channels)
        self.peak = np.zeros(n_channels)
        self.clip_total = 0
        self.clip_runs = 0
        self.clip_max_run = 0
        self._carry = np.zeros(n_channels, dtype=np.int64)

    def process(self, block):
        self.frames += block.shape[0]
        self.total += block.sum(axis=0)
        self.sum_sq += (block * block).sum(axis=0)
        self.peak = np.maximum(self.peak, np.abs(block).max(axis=0))
        flags = np.abs(block) >= CLIP_THRESHOLD
        self.clip_total += int(flags.sum())
        for ch in range(self.n_channels):
            self._update_runs(ch, flags[:, ch])

    def _record_run(self, length):
        if length >= 2:
            self.clip_runs += 1
            self.clip_max_run = max(self.clip_max_run, int(length))

    def _update_runs(self, ch, c):
        if not c.any():
            if self._carry[ch]:
                self._record_run(self._carry[ch])
                self._carry[ch] = 0
            return
        padded = np.concatenate(([0], c.astype(np.int8), [0]))
        d = np.diff(padded)
        starts = np.flatnonzero(d == 1)
        ends = np.flatnonzero(d == -1)
        lengths = (ends - starts).astype(np.int64)
        if self._carry[ch]:
            if starts.size and starts[0] == 0:
                lengths[0] += self._carry[ch]
            else:
                self._record_run(self._carry[ch])
            self._carry[ch] = 0
        open_at_end = bool(starts.size) and ends[-1] == c.size
        for i in range(lengths.size):
            if open_at_end and i == lengths.size - 1:
                self._carry[ch] = lengths[i]
            else:
                self._record_run(lengths[i])

    def flush(self):
        for ch in range(self.n_channels):
            if self._carry[ch]:
                self._record_run(self._carry[ch])
                self._carry[ch] = 0

    def summary(self):
        rms_per_channel = []
        for ch in range(self.n_channels):
            rms_per_channel.append(_db(np.sqrt(self.sum_sq[ch] / self.frames)))
        rms_overall = _db(
            np.sqrt(self.sum_sq.sum() / (self.frames * self.n_channels))
        )
        dc_per_channel = (self.total / self.frames).tolist()
        clipping = None
        if self.clip_total > 0:
            clipping = {
                "total_samples": self.clip_total,
                "runs": self.clip_runs,
                "max_run_samples": self.clip_max_run,
            }
        return {
            "frames": self.frames,
            "sample_peak_dbfs": _db(float(self.peak.max())),
            "sample_peak_dbfs_per_channel": [_db(float(p)) for p in self.peak],
            "rms_db": rms_overall,
            "rms_db_per_channel": rms_per_channel,
            "dc_offset_per_channel": dc_per_channel,
            "clipping": clipping,
        }


class CorrelationAccumulator:
    def __init__(self, hop_frames):
        self.values = []
        self.s_lr = 0.0
        self.s_ll = 0.0
        self.s_rr = 0.0
        self._hop = HopAggregator(hop_frames)

    def process(self, block):
        self._hop.process(block, self._accumulate)

    def _accumulate(self, h):
        left = h[:, 0]
        right = h[:, 1]
        lr = float(np.dot(left, right))
        ll = float(np.dot(left, left))
        rr = float(np.dot(right, right))
        self.s_lr += lr
        self.s_ll += ll
        self.s_rr += rr
        denom = np.sqrt(ll * rr)
        self.values.append(lr / denom if denom > 0.0 else np.nan)

    def flush(self):
        self._hop.flush(self._accumulate)

    def summary(self):
        v = np.asarray(self.values)
        v = v[np.isfinite(v)]
        global_corr = None
        denom = np.sqrt(self.s_ll * self.s_rr)
        if denom > 0.0:
            global_corr = float(self.s_lr / denom)
        corr_min = None
        if v.size >= 10:
            kernel = np.ones(10) / 10.0
            smoothed = np.convolve(v, kernel, "valid")
            corr_min = float(smoothed.min())
        elif v.size:
            corr_min = float(v.min())
        return global_corr, corr_min


class WaveformAccumulator:
    def __init__(self, hop_frames, max_points=MAX_WAVEFORM_POINTS):
        self.mins = []
        self.maxs = []
        self.max_points = max_points
        self._hop = HopAggregator(hop_frames)

    def process(self, block):
        self._hop.process(block, self._accumulate)

    def _accumulate(self, h):
        m = h.mean(axis=1)
        self.mins.append(float(m.min()))
        self.maxs.append(float(m.max()))

    def flush(self):
        self._hop.flush(self._accumulate)

    def summary(self):
        mins = np.asarray(self.mins, dtype=np.float64)
        maxs = np.asarray(self.maxs, dtype=np.float64)
        if mins.size == 0:
            return [], []
        if mins.size > self.max_points:
            factor = int(np.ceil(mins.size / self.max_points))
            idx = np.arange(0, mins.size, factor)
            mins = np.minimum.reduceat(mins, idx)
            maxs = np.maximum.reduceat(maxs, idx)
        return mins.tolist(), maxs.tolist()


class SpectrumAccumulator:
    def __init__(self, fs, every_n_blocks=4, nperseg=8192):
        self.fs = fs
        self.every = every_n_blocks
        self.nperseg = nperseg
        self.acc = None
        self.freqs = None
        self.count = 0
        self.block_index = 0

    def process(self, block):
        index = self.block_index
        self.block_index += 1
        if index % self.every:
            return
        x = block.mean(axis=1) if block.shape[1] > 1 else block[:, 0]
        n = min(self.nperseg, x.size)
        if n < 256:
            return
        f, p = welch(x, self.fs, nperseg=n)
        if self.acc is None:
            self.acc = p.copy()
            self.freqs = f
        else:
            self.acc += p
        self.count += 1

    def summary(self):
        if self.count == 0:
            return None
        avg = self.acc / self.count
        edges = THIRD_OCTAVE_CENTERS * 2.0 ** (1.0 / 6.0)
        lower = THIRD_OCTAVE_CENTERS / 2.0 ** (1.0 / 6.0)
        bands = []
        for lo, hi in zip(lower, edges):
            mask = (self.freqs >= lo) & (self.freqs < hi)
            if not mask.any():
                bands.append(None)
                continue
            energy = float(avg[mask].sum())
            bands.append(float(10.0 * np.log10(energy + 1e-20)))
        return {
            "freqs": [float(c) for c in THIRD_OCTAVE_CENTERS],
            "db": bands,
        }


class AnalysisConfig:
    def __init__(
        self,
        max_duration_minutes=None,
        compute_spectrum=True,
        compute_waveform=True,
        compute_correlation=True,
    ):
        self.max_duration_minutes = max_duration_minutes
        self.compute_spectrum = compute_spectrum
        self.compute_waveform = compute_waveform
        self.compute_correlation = compute_correlation


def analyze_source(provider, config=None):
    config = config or AnalysisConfig()
    sr, nch, frames = provider.info()
    duration = frames / sr
    if (
        config.max_duration_minutes is not None
        and duration > config.max_duration_minutes * 60.0
    ):
        raise ValueError(
            "Duration exceeds the configured limit "
            f"({config.max_duration_minutes:g} min)."
        )
    hop = max(1, int(round(sr * HOP_SECONDS)))
    block = hop * BLOCK_HOPS
    loudness = LoudnessAccumulator(sr, nch, channel_weights(nch))
    level = LevelAccumulator(nch)
    correlation = (
        CorrelationAccumulator(hop) if nch == 2 and config.compute_correlation else None
    )
    waveform = WaveformAccumulator(hop) if config.compute_waveform else None
    spectrum = SpectrumAccumulator(sr) if config.compute_spectrum else None
    for b in provider.blocks(block):
        block64 = np.asarray(b, dtype=np.float64)
        loudness.process(block64)
        level.process(block64)
        if correlation is not None:
            correlation.process(block64)
        if waveform is not None:
            waveform.process(block64)
        if spectrum is not None:
            spectrum.process(block64)

    level.flush()
    loudness_result = loudness.finish()

    scanner = TruePeakScanner(nch)
    tp_block = hop * TRUE_PEAK_BLOCK_HOPS
    for b in provider.blocks(tp_block):
        scanner.process(np.asarray(b, dtype=np.float64))
    tp_linear = scanner.finish()
    analysis = {}
    analysis.update(level.summary())
    analysis["true_peak_dbtp"] = _db(float(tp_linear.max()))
    analysis["true_peak_dbtp_per_channel"] = [
        _db(float(v)) for v in tp_linear
    ]
    analysis.update({
        "loudness_integrated_lufs": loudness_result["integrated_lufs"],
        "momentary_max_lufs": loudness_result["momentary_max_lufs"],
        "short_term_max_lufs": loudness_result["short_term_max_lufs"],
        "lra_lu": loudness_result["lra_lu"],
    })

    plr = None
    if analysis["true_peak_dbtp"] is not None and analysis["loudness_integrated_lufs"] is not None:
        plr = analysis["true_peak_dbtp"] - analysis["loudness_integrated_lufs"]
    crest = None
    if analysis["sample_peak_dbfs"] is not None and analysis["rms_db"] is not None:
        crest = analysis["sample_peak_dbfs"] - analysis["rms_db"]
    analysis["plr_db"] = plr
    analysis["crest_factor_db"] = crest

    if correlation is not None:
        correlation.flush()
        global_corr, corr_min = correlation.summary()
        analysis["phase_correlation"] = global_corr
        analysis["phase_correlation_min"] = corr_min
        rms_l = analysis["rms_db_per_channel"][0]
        rms_r = analysis["rms_db_per_channel"][1]
        analysis["lr_balance_db"] = (
            rms_l - rms_r
            if rms_l is not None and rms_r is not None
            else None
        )
    else:
        analysis["phase_correlation"] = None
        analysis["phase_correlation_min"] = None
        analysis["lr_balance_db"] = None

    wave_min, wave_max = ([], [])
    if waveform is not None:
        waveform.flush()
        wave_min, wave_max = waveform.summary()

    spectrum_result = spectrum.summary() if spectrum is not None else None

    return {
        "sample_rate": int(sr),
        "channels": int(nch),
        "duration_s": float(round(duration, 3)),
        "analysis": analysis,
        "timeline": {
            "t_momentary": loudness_result["t_momentary"],
            "momentary": loudness_result["momentary"],
            "t_short_term": loudness_result["t_short_term"],
            "short_term": loudness_result["short_term"],
        },
        "spectrum": spectrum_result,
        "waveform": {"min": wave_min, "max": wave_max},
    }


def analyze_file(path, config=None):
    return analyze_source(FileProvider(path), config)


def analyze_array(audio, sr, config=None):
    return analyze_source(ArrayProvider(audio, sr), config)


def _clean_number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if np.isnan(number) or np.isinf(number):
        return None
    return number


def _clean_value(value):
    if isinstance(value, dict):
        return {k: _clean_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean_value(v) for v in value]
    return _clean_number(value)


def _round_list(values, decimals=2):
    return [None if v is None else float(round(float(v), decimals)) for v in values]


def _downsample(series, max_points=MAX_TIMELINE_POINTS, keep_max=True):
    arr = np.asarray(series, dtype=np.float64)
    if arr.size == 0:
        return []
    if arr.size > max_points:
        factor = int(np.ceil(arr.size / max_points))
        idx = np.arange(0, arr.size, factor)
        if keep_max:
            arr = np.maximum.reduceat(arr, idx)
        else:
            counts = np.diff(np.append(idx, arr.size))
            total = np.add.reduceat(arr, idx)
            arr = total / counts
    return [
        round(float(v), 2) if np.isfinite(v) else None
        for v in arr
    ]


def compact_result(result):
    analysis = {}
    for key, value in result["analysis"].items():
        analysis[key] = _clean_value(value)
    timeline = {
        "t_momentary": _downsample(result["timeline"]["t_momentary"], keep_max=False),
        "momentary": _downsample(result["timeline"]["momentary"]),
        "t_short_term": _downsample(result["timeline"]["t_short_term"], keep_max=False),
        "short_term": _downsample(result["timeline"]["short_term"]),
    }
    waveform = result.get("waveform") or {"min": [], "max": []}
    spectrum = result.get("spectrum")
    return {
        "sample_rate": result["sample_rate"],
        "channels": result["channels"],
        "duration_s": result["duration_s"],
        "analysis": analysis,
        "timeline": timeline,
        "spectrum": (
            {
                "freqs": _round_list(spectrum["freqs"], 1),
                "db": _round_list(spectrum["db"]),
            }
            if spectrum is not None
            else None
        ),
        "waveform": {
            "min": _round_list(waveform["min"], 4),
            "max": _round_list(waveform["max"], 4),
        },
    }
