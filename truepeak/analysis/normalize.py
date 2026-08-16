import os
import uuid

import numpy as np
import soundfile as sf

from .dsp import ArrayProvider, load_audio
from .meter import LoudnessAccumulator
from .peaks import TruePeakScanner
from .pipeline import BLOCK_HOPS, HOP_SECONDS, LevelAccumulator

try:
    from pedalboard import Limiter as PedalboardLimiter
except Exception:
    PedalboardLimiter = None


def _fast_meter(audio, sr):
    hop = max(1, int(round(sr * HOP_SECONDS)))
    nch = audio.shape[1]
    loudness = LoudnessAccumulator(sr, nch, (1.0,) * nch)
    level = LevelAccumulator(nch)
    block = hop * BLOCK_HOPS
    provider = ArrayProvider(audio, sr)
    for b in provider.blocks(block):
        block64 = np.asarray(b, dtype=np.float64)
        loudness.process(block64)
        level.process(block64)
    level.flush()
    scanner = TruePeakScanner(nch)
    for b in provider.blocks(hop * 16):
        scanner.process(np.asarray(b, dtype=np.float64))
    tp = scanner.finish()
    peak_db = None
    if tp.max() > 0.0:
        peak_db = float(20.0 * np.log10(tp.max()))
    return loudness.finish(), peak_db


def _measure_true_peak(audio, sr):
    nch = audio.shape[1]
    hop = max(1, int(round(sr * HOP_SECONDS)))
    provider = ArrayProvider(audio, sr)
    scanner = TruePeakScanner(nch)
    for b in provider.blocks(hop * 16):
        scanner.process(np.asarray(b, dtype=np.float64))
    tp = scanner.finish()
    if tp.max() <= 0.0:
        return None
    return float(20.0 * np.log10(tp.max()))


def process_normalization(path, target_lufs, max_tp_dbtp, use_limiter, config):
    audio, sr = load_audio(path)
    duration = audio.shape[0] / sr
    if (
        config.max_duration_minutes is not None
        and duration > config.max_duration_minutes * 60.0
    ):
        raise ValueError(
            "Duration exceeds the configured limit for normalization "
            f"({config.max_duration_minutes:g} min)."
        )

    before_meter, before_peak = _fast_meter(audio, sr)
    integrated = before_meter["integrated_lufs"]
    if integrated is None:
        raise ValueError(
            "Cannot normalize: file is silent or too short for loudness measurement."
        )

    gain_db = target_lufs - integrated
    limiter_applied = False
    applied_gain_db = gain_db

    if before_peak is not None and before_peak + gain_db > max_tp_dbtp:
        if use_limiter and PedalboardLimiter is not None:
            linear_gain = 10.0 ** (gain_db / 20.0)
            scaled = audio * linear_gain
            limiter = PedalboardLimiter(threshold_db=max_tp_dbtp)
            processed = np.asarray(limiter(scaled, sr), dtype=np.float64)
            limiter_applied = True
            final_tp = _measure_true_peak(processed, sr)
            if final_tp is not None and final_tp > max_tp_dbtp:
                trim = max_tp_dbtp - final_tp
                processed = processed * 10.0 ** (trim / 20.0)
        else:
            applied_gain_db = max_tp_dbtp - before_peak
            processed = audio * 10.0 ** (applied_gain_db / 20.0)
    else:
        processed = audio * 10.0 ** (gain_db / 20.0)

    after_meter, after_peak = _fast_meter(processed, sr)

    out_name = f"normalized_{uuid.uuid4().hex}.wav"
    out_path = os.path.join(config.temp_dir, out_name)
    os.makedirs(config.temp_dir, exist_ok=True)
    sf.write(out_path, processed, sr, subtype="PCM_24")

    return {
        "out_path": out_path,
        "gain_db": float(round(applied_gain_db, 2)),
        "requested_gain_db": float(round(gain_db, 2)),
        "limiter_applied": limiter_applied,
        "before": {
            "loudness_integrated_lufs": integrated,
            "true_peak_dbtp": before_peak,
        },
        "after": {
            "loudness_integrated_lufs": after_meter["integrated_lufs"],
            "true_peak_dbtp": after_peak,
        },
        "target_lufs": float(target_lufs),
        "max_tp_dbtp": float(max_tp_dbtp),
    }
