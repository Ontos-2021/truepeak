from truepeak.analysis.targets import PLATFORMS, build_verdicts


def test_platforms_have_known_targets():
    by_id = {p["id"]: p for p in PLATFORMS}
    assert by_id["spotify"]["target_lufs"] == -14.0
    assert by_id["apple_music"]["target_lufs"] == -16.0
    assert by_id["amazon_music"]["max_tp_dbtp"] == -2.0
    assert by_id["ebu_r128"]["target_lufs"] == -23.0


def test_verdict_loud_playback_cut():
    analysis = {
        "loudness_integrated_lufs": -9.0,
        "true_peak_dbtp": -1.5,
    }
    verdicts = {v["id"]: v for v in build_verdicts(analysis)}
    spotify = verdicts["spotify"]
    assert spotify["playback_gain_db"] == -5.0
    assert spotify["status"] == "loud"
    assert spotify["true_peak_ok"] is True


def test_verdict_true_peak_exceeds():
    analysis = {
        "loudness_integrated_lufs": -14.0,
        "true_peak_dbtp": -0.3,
    }
    verdicts = {v["id"]: v for v in build_verdicts(analysis)}
    assert verdicts["spotify"]["true_peak_ok"] is False
    assert verdicts["amazon_music"]["true_peak_ok"] is False


def test_verdict_quiet_boost():
    analysis = {
        "loudness_integrated_lufs": -20.0,
        "true_peak_dbtp": -3.0,
    }
    verdicts = {v["id"]: v for v in build_verdicts(analysis)}
    assert verdicts["spotify"]["playback_gain_db"] == 6.0
    assert verdicts["spotify"]["status"] == "quiet"


def test_verdict_missing_metrics():
    analysis = {}
    verdicts = build_verdicts(analysis)
    assert all(v["playback_gain_db"] is None for v in verdicts)
    assert all(v["true_peak_ok"] is None for v in verdicts)
