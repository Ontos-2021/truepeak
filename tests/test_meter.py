
import numpy as np
import pytest

from truepeak.analysis import analyze_array
from truepeak.analysis.meter import (
    integrated_loudness,
    loudness_range,
    lufs_from_mean_square,
    sliding_mean,
)

SR = 44100


def make_sine(duration, amplitude, freq=997.0, channels=2, phase=0.0, sr=SR):
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    mono = amplitude * np.sin(2 * np.pi * freq * t + phase)
    if channels == 1:
        return mono.astype(np.float32), sr
    return np.stack([mono, mono], axis=1).astype(np.float32), sr


def test_lufs_alignment_sine_stereo_minus20():
    audio, sr = make_sine(8.0, 0.1)
    result = analyze_array(audio, sr)
    integrated = result["analysis"]["loudness_integrated_lufs"]
    assert integrated is not None
    assert abs(integrated - (-20.04)) < 0.15


def test_lufs_alignment_sine_mono_minus20():
    audio, sr = make_sine(8.0, 0.1, channels=1)
    result = analyze_array(audio, sr)
    integrated = result["analysis"]["loudness_integrated_lufs"]
    assert abs(integrated - (-23.05)) < 0.15


def test_momentary_short_term_match_integrated_for_constant_signal():
    audio, sr = make_sine(8.0, 0.1)
    result = analyze_array(audio, sr)
    analysis = result["analysis"]
    assert abs(analysis["momentary_max_lufs"] - analysis["loudness_integrated_lufs"]) < 0.2
    assert abs(analysis["short_term_max_lufs"] - analysis["loudness_integrated_lufs"]) < 0.2


def test_lra_two_level_signal():
    loud, sr = make_sine(6.0, 0.3422)
    quiet, sr = make_sine(6.0, 0.0609)
    audio = np.concatenate([loud, quiet], axis=0)
    result = analyze_array(audio, sr)
    lra = result["analysis"]["lra_lu"]
    assert lra is not None
    assert abs(lra - 15.5) < 2.0


def test_integrated_absolute_gate_excludes_silence():
    silence = np.zeros((int(SR * 2), 2), dtype=np.float32)
    tone, sr = make_sine(8.0, 0.1)
    audio = np.concatenate([silence, tone], axis=0)
    result = analyze_array(audio, sr)
    integrated = result["analysis"]["loudness_integrated_lufs"]
    assert abs(integrated - (-20.04)) < 0.3


def test_integrated_relative_gate_excludes_quiet_blocks():
    loud, sr = make_sine(4.0, 0.3422)
    quiet, sr = make_sine(4.0, 0.0609)
    audio = np.concatenate([loud, quiet], axis=0)
    result = analyze_array(audio, sr)
    integrated = result["analysis"]["loudness_integrated_lufs"]
    assert integrated is not None
    assert integrated > -11.0
    assert abs(integrated - (-9.47)) < 0.5


def test_lufs_unit_math():
    z = np.array([0.01, 0.01, 0.01])
    levels = lufs_from_mean_square(z)
    assert np.allclose(levels, -20.691, atol=1e-6)
    assert np.isclose(integrated_loudness(z), -20.691, atol=1e-6)


def test_sliding_mean():
    z = np.arange(6, dtype=np.float64)
    sm = sliding_mean(z, 3)
    assert len(sm) == 4
    assert np.allclose(sm[0], 1.0)


def test_loudness_range_constant_signal_is_zero():
    levels = np.full(200, -20.69)
    assert loudness_range(levels) == pytest.approx(0.0, abs=0.01)


def test_matches_pyloudnorm_reference():
    pyln = pytest.importorskip("pyloudnorm")
    audio, sr = make_sine(8.0, 0.1)
    reference = pyln.Meter(sr).integrated_loudness(audio)
    result = analyze_array(audio, sr)
    assert abs(result["analysis"]["loudness_integrated_lufs"] - reference) < 0.1
