import numpy as np

from truepeak.analysis import analyze_array

SR = 48000


def make_sine(duration, amplitude, freq, phase=0.0, sr=SR):
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    mono = amplitude * np.sin(2 * np.pi * freq * t + phase)
    return np.stack([mono, mono], axis=1).astype(np.float32), sr


def test_sample_peak_basic_sine():
    audio, sr = make_sine(2.0, 0.5, 1000.0)
    result = analyze_array(audio, sr)
    assert abs(result["analysis"]["sample_peak_dbfs"] - (-6.02)) < 0.2
    assert abs(result["analysis"]["true_peak_dbtp"] - (-6.02)) < 0.5


def test_inter_sample_peak_detected():
    audio, sr = make_sine(2.0, 0.5, SR / 4.0, phase=np.pi / 4)
    result = analyze_array(audio, sr)
    analysis = result["analysis"]
    assert analysis["true_peak_dbtp"] is not None
    assert analysis["sample_peak_dbfs"] is not None
    assert analysis["true_peak_dbtp"] - analysis["sample_peak_dbfs"] > 2.5
    assert abs(analysis["true_peak_dbtp"] - (-6.02)) < 0.5


def test_chunked_scan_matches_full_resample():
    from scipy.signal import resample_poly

    from truepeak.analysis.peaks import TruePeakScanner

    duration = 3.0
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    audio = (0.95 * np.sin(2 * np.pi * 997.0 * t)).astype(np.float32)
    reference = float(
        np.abs(resample_poly(audio.astype(np.float64), 4, 1)).max()
    )
    for block in (70560, 10000, 300):
        scanner = TruePeakScanner(1)
        for i in range(0, len(audio), block):
            scanner.process(np.asarray(audio[i:i + block], dtype=np.float64))
        measured = float(scanner.finish().max())
        assert abs(measured - reference) < 1e-9


def test_true_peak_never_below_sample_peak():
    rng = np.random.default_rng(42)
    for _ in range(3):
        noise = rng.standard_normal((SR * 2, 2)).astype(np.float32) * 0.3
        result = analyze_array(noise, SR)
        analysis = result["analysis"]
        if analysis["true_peak_dbtp"] is not None:
            assert analysis["true_peak_dbtp"] >= analysis["sample_peak_dbfs"] - 1e-6


def test_true_peak_per_channel():
    duration = 2.0
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    left = 0.4 * np.sin(2 * np.pi * 997.0 * t)
    right = 0.2 * np.sin(2 * np.pi * 997.0 * t)
    audio = np.stack([left, right], axis=1).astype(np.float32)
    result = analyze_array(audio, SR)
    per = result["analysis"]["true_peak_dbtp_per_channel"]
    assert abs(per[0] - per[1]) > 5.0


def test_silent_file_has_no_peaks():
    audio = np.zeros((SR * 2, 2), dtype=np.float32)
    result = analyze_array(audio, SR)
    assert result["analysis"]["sample_peak_dbfs"] is None
    assert result["analysis"]["true_peak_dbtp"] is None
