"""Parity tests: the browser DSP engine (static/dsp.js, run via Node) must
produce the same measurements as the Python pipeline within tight tolerances.
"""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from truepeak.analysis import analyze_array

NODE = shutil.which("node")
JS_RUNNER = Path(__file__).parent / "js_parity.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="node not available")


def _run_js(path):
    proc = subprocess.run(
        [NODE, str(JS_RUNNER), str(path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _compare(js, wav_path):
    # Python must analyze the same quantized samples the JS engine read.
    audio, sr = sf.read(str(wav_path), dtype="float64", always_2d=True)
    py = analyze_array(audio, sr)
    a_js = js["analysis"]
    a_py = py["analysis"]
    assert a_js["loudness_integrated_lufs"] == pytest.approx(
        a_py["loudness_integrated_lufs"], abs=0.05
    )
    assert a_js["true_peak_dbtp"] == pytest.approx(a_py["true_peak_dbtp"], abs=0.05)
    assert a_js["sample_peak_dbfs"] == pytest.approx(
        a_py["sample_peak_dbfs"], abs=0.01
    )
    assert a_js["rms_db"] == pytest.approx(a_py["rms_db"], abs=0.02)
    assert a_js["crest_factor_db"] == pytest.approx(
        a_py["crest_factor_db"], abs=0.05
    )
    assert a_js["phase_correlation"] == pytest.approx(
        a_py["phase_correlation"], abs=0.001
    )
    if a_py["lra_lu"] is not None:
        assert a_js["lra_lu"] == pytest.approx(a_py["lra_lu"], abs=0.3)
    assert js["duration_s"] == pytest.approx(py["duration_s"], abs=0.01)
    assert len(js["spectrum"]["db"]) == len(py["spectrum"]["db"])
    for v_js, v_py in zip(js["spectrum"]["db"], py["spectrum"]["db"]):
        if v_py is None:
            continue
        assert v_js == pytest.approx(v_py, abs=0.5)


def test_js_parity_tone(tmp_path):
    sr = 44100
    t = np.linspace(0, 5.0, int(sr * 5.0), endpoint=False)
    mono = 0.1 * np.sin(2 * np.pi * 997.0 * t)
    audio = np.stack([mono, mono], axis=1)
    wav = tmp_path / "tone.wav"
    sf.write(str(wav), audio, sr, subtype="PCM_16")
    _compare(_run_js(wav), wav)


def test_js_parity_dynamic_music(tmp_path):
    rng = np.random.default_rng(7)
    sr = 48000
    t = np.linspace(0, 12.0, int(sr * 12.0), endpoint=False)
    env = 0.05 + 0.4 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.25 * t))
    left = env * np.sin(2 * np.pi * 220.0 * t) + 0.02 * rng.standard_normal(t.size)
    right = env * np.sin(2 * np.pi * 330.0 * t) + 0.02 * rng.standard_normal(t.size)
    audio = np.stack([left, right], axis=1)
    wav = tmp_path / "music.wav"
    sf.write(str(wav), audio, sr, subtype="PCM_16")
    _compare(_run_js(wav), wav)


def test_js_parity_timeline_length(tmp_path):
    sr = 44100
    t = np.linspace(0, 60.0, int(sr * 60.0), endpoint=False)
    audio = 0.1 * np.sin(2 * np.pi * 440.0 * t)[:, None]
    wav = tmp_path / "long.wav"
    sf.write(str(wav), audio, sr, subtype="PCM_16")
    js = _run_js(wav)
    assert len(js["timeline"]["momentary"]) <= 2400
    assert len(js["waveform"]["min"]) <= 2048
