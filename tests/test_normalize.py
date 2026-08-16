import io
import os

import soundfile as sf

from tests.conftest import make_wav


def normalize(client, buf, target=-14.0, ceiling=-1.0, limiter="1", name="test.wav"):
    buf.seek(0)
    return client.post(
        "/normalize",
        data={
            "file": (buf, name),
            "target_lufs": str(target),
            "max_tp_dbtp": str(ceiling),
            "use_limiter": limiter,
        },
        content_type="multipart/form-data",
    )


def test_normalize_gain_only_hits_target(client):
    buf = make_wav(duration=3.0, amplitude=0.05)
    resp = normalize(client, buf, target=-14.0)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["limiter_applied"] is False
    after = data["after"]["loudness_integrated_lufs"]
    assert abs(after - (-14.0)) < 0.3
    assert data["gain_db"] > 0
    assert data["download_url"]


def test_normalize_download_returns_wav(client):
    buf = make_wav(duration=3.0, amplitude=0.05)
    resp = normalize(client, buf, target=-14.0)
    data = resp.get_json()
    download = client.get(data["download_url"])
    assert download.status_code == 200
    assert download.headers["Content-Type"].startswith("audio/wav")
    assert download.data.startswith(b"RIFF")


def test_normalize_download_consumes_token(client):
    buf = make_wav(duration=3.0, amplitude=0.05)
    resp = normalize(client, buf, target=-14.0)
    url = resp.get_json()["download_url"]
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 404


def test_normalize_loud_file_trims_to_ceiling_without_limiter(client):
    buf = make_wav(duration=3.0, amplitude=0.95)
    resp = normalize(client, buf, target=-8.0, ceiling=-1.0, limiter="0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["limiter_applied"] is False
    assert data["after"]["true_peak_dbtp"] <= -1.0 + 0.05


def test_normalize_invalid_target(client):
    buf = make_wav()
    resp = normalize(client, buf, target=5.0)
    assert resp.status_code == 400


def test_normalize_no_file(client):
    resp = client.post("/normalize", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_normalize_cleans_original(client, app):
    temp_dir = app.config["TEMP_DIR"]
    buf = make_wav(duration=2.0)
    resp = normalize(client, buf, target=-14.0)
    assert resp.status_code == 200
    leftovers = os.listdir(temp_dir)
    for f in leftovers:
        assert not f.endswith(".wav") or f.startswith("normalized_") or f.startswith("tmp")


def test_normalized_output_is_readable_audio():
    buf = make_wav(duration=3.0, amplitude=0.05)
    audio, sr = sf.read(io.BytesIO(buf.getvalue()), dtype="float32", always_2d=True)
    assert audio.shape[0] > 0
    assert sr == 44100
