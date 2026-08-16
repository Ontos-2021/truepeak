
import numpy as np
import pytest

from truepeak.analysis import (
    AnalysisConfig,
    analyze_array,
    compact_result,
)

SR = 44100


def make_pair(duration, left_amp, right_amp, sr=SR):
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    left = left_amp * np.sin(2 * np.pi * 997.0 * t)
    right = right_amp * np.sin(2 * np.pi * 997.0 * t)
    return np.stack([left, right], axis=1).astype(np.float32), sr


def test_rms_full_scale_sine():
    audio, sr = make_pair(2.0, 1.0, 1.0)
    result = analyze_array(audio, sr)
    assert abs(result["analysis"]["rms_db"] - (-3.01)) < 0.1
    assert abs(result["analysis"]["rms_db_per_channel"][0] - (-3.01)) < 0.1


def test_plr_and_crest():
    audio, sr = make_pair(2.0, 0.5, 0.5)
    result = analyze_array(audio, sr)
    analysis = result["analysis"]
    assert analysis["plr_db"] is not None
    assert analysis["crest_factor_db"] is not None
    assert abs(analysis["plr_db"] - analysis["true_peak_dbtp"] + analysis["loudness_integrated_lufs"]) < 0.01


def test_phase_correlation_identical_channels():
    audio, sr = make_pair(2.0, 0.5, 0.5)
    result = analyze_array(audio, sr)
    assert result["analysis"]["phase_correlation"] == pytest.approx(1.0, abs=0.01)


def test_phase_correlation_inverted_channels():
    audio, sr = make_pair(2.0, 0.5, -0.5)
    result = analyze_array(audio, sr)
    assert result["analysis"]["phase_correlation"] == pytest.approx(-1.0, abs=0.01)


def test_phase_correlation_uncorrelated_noise():
    rng = np.random.default_rng(7)
    left = rng.standard_normal(SR * 2)
    right = rng.standard_normal(SR * 2)
    audio = np.stack([left, right], axis=1).astype(np.float32)
    result = analyze_array(audio, SR)
    assert abs(result["analysis"]["phase_correlation"]) < 0.2


def test_lr_balance():
    audio, sr = make_pair(2.0, 0.5, 0.25)
    result = analyze_array(audio, sr)
    assert abs(result["analysis"]["lr_balance_db"] - 6.02) < 0.2


def test_clipping_detection():
    t = np.linspace(0, 2.0, int(SR * 2.0), endpoint=False)
    clipped = np.clip(1.2 * np.sin(2 * np.pi * 997.0 * t), -1.0, 1.0)
    audio = np.stack([clipped, clipped], axis=1).astype(np.float32)
    result = analyze_array(audio, SR)
    clipping = result["analysis"]["clipping"]
    assert clipping is not None
    assert clipping["runs"] >= 1
    assert clipping["total_samples"] > 0


def test_dc_offset():
    t = np.linspace(0, 1.0, int(SR), endpoint=False)
    mono = 0.3 * np.sin(2 * np.pi * 997.0 * t) + 0.1
    audio = np.stack([mono, mono], axis=1).astype(np.float32)
    result = analyze_array(audio, SR)
    dc = result["analysis"]["dc_offset_per_channel"]
    assert abs(dc[0] - 0.1) < 0.01


def test_spectrum_and_waveform_present():
    audio, sr = make_pair(2.0, 0.5, 0.5)
    result = analyze_array(audio, sr)
    assert result["spectrum"] is not None
    assert len(result["spectrum"]["freqs"]) == 30
    assert len(result["spectrum"]["db"]) == 30
    assert len(result["waveform"]["min"]) > 0
    assert len(result["waveform"]["min"]) == len(result["waveform"]["max"])


def test_waveform_decimated_to_max_points():
    audio, sr = make_pair(300.0, 0.3, 0.3)
    result = analyze_array(audio, sr)
    assert len(result["waveform"]["min"]) <= 2048


def test_timeline_downsampled_and_cleaned():
    audio, sr = make_pair(300.0, 0.3, 0.3)
    result = analyze_array(audio, sr)
    compact = compact_result(result)
    assert len(compact["timeline"]["momentary"]) <= 2400
    assert len(compact["timeline"]["t_momentary"]) == len(compact["timeline"]["momentary"])


def test_silent_timeline_has_no_nan():
    audio = np.zeros((int(SR * 4), 2), dtype=np.float32)
    result = analyze_array(audio, SR)
    compact = compact_result(result)
    assert compact["analysis"]["loudness_integrated_lufs"] is None
    assert compact["timeline"]["momentary"] == []
    assert compact["analysis"]["rms_db"] is None


def test_mono_file_has_no_stereo_metrics():
    audio = np.zeros((int(SR), 1), dtype=np.float32) * 0 + 0.3
    t = np.linspace(0, 1.0, int(SR), endpoint=False)
    audio = (0.3 * np.sin(2 * np.pi * 997.0 * t)).astype(np.float32)[:, None]
    result = analyze_array(audio, SR)
    assert result["analysis"]["phase_correlation"] is None
    assert result["analysis"]["lr_balance_db"] is None


def test_duration_limit_enforced():
    audio, sr = make_pair(2.0, 0.3, 0.3)
    config = AnalysisConfig(max_duration_minutes=0.01)
    with pytest.raises(ValueError):
        analyze_array(audio, sr, config)


def test_compact_result_cleans_non_finite():
    raw = {
        "sample_rate": 44100,
        "channels": 2,
        "duration_s": 1.0,
        "analysis": {
            "loudness_integrated_lufs": float("nan"),
            "true_peak_dbtp": float("-inf"),
            "rms_db": -3.0,
            "clipping": {"runs": 0, "max_run_samples": 0, "total_samples": 0},
        },
        "timeline": {
            "t_momentary": [0.1, 0.2],
            "momentary": [float("-inf"), -10.5],
            "t_short_term": [0.5],
            "short_term": [-10.4],
        },
        "spectrum": None,
        "waveform": {"min": [0.1], "max": [0.2]},
    }
    compact = compact_result(raw)
    assert compact["analysis"]["loudness_integrated_lufs"] is None
    assert compact["analysis"]["true_peak_dbtp"] is None
    assert compact["timeline"]["momentary"] == [None, -10.5]
