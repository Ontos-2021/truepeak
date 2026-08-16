import io
import json
import os

from tests.conftest import make_wav, upload


def test_index_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"TruePeak" in resp.data


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_targets_endpoint(client):
    resp = client.get("/api/targets")
    assert resp.status_code == 200
    platforms = resp.get_json()["platforms"]
    ids = {p["id"] for p in platforms}
    assert "spotify" in ids
    assert "apple_music" in ids


def test_analyze_single_file(client):
    resp = upload(client, make_wav())
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert "error" not in result
    analysis = result["analysis"]
    for key in (
        "sample_peak_dbfs",
        "true_peak_dbtp",
        "rms_db",
        "loudness_integrated_lufs",
        "momentary_max_lufs",
        "short_term_max_lufs",
        "lra_lu",
        "plr_db",
        "crest_factor_db",
    ):
        assert key in analysis
    assert isinstance(result["timeline"]["momentary"], list)
    assert len(result["spectrum"]["db"]) == 30
    assert len(result["waveform"]["min"]) > 0
    assert len(result["verdicts"]) >= 9
    assert data["album"]["track_count"] == 1
    json.dumps(data)


def test_analyze_multiple_files_album(client):
    resp = upload(client, make_wav(amplitude=0.5), make_wav(amplitude=0.2))
    assert resp.status_code == 200
    data = resp.get_json()
    album = data["album"]
    assert album["track_count"] == 2
    assert album["lufs_spread_lu"] is not None
    assert album["lufs_spread_lu"] > 5.0
    assert album["max_true_peak_dbtp"] is not None
    assert len(album["tracks"]) == 2


def test_analyze_invalid_extension(client):
    buf = io.BytesIO(b"garbage")
    resp = upload(client, buf, names=["not_audio.txt"])
    assert resp.status_code == 400
    assert "Invalid file type" in resp.get_json()["error"]


def test_analyze_no_files(client):
    resp = client.post("/analyze", data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_analyze_corrupted_file_does_not_fail_batch(client):
    good = make_wav()
    bad = io.BytesIO(b"this is definitely not audio data" * 50)
    resp = upload(client, good, bad)
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["results"]) == 2
    assert any("error" in r for r in data["results"])
    assert data["album"]["error_count"] == 1


def test_analyze_cleans_temp_files(client, app):
    temp_dir = app.config["TEMP_DIR"]
    upload(client, make_wav())
    upload(client, make_wav(), make_wav())
    leftovers = os.listdir(temp_dir)
    assert not [f for f in leftovers if not f.startswith("normalized_")]


def test_export_pdf(client):
    resp = upload(client, make_wav(), make_wav(freq=300.0))
    assert resp.status_code == 200
    payload = resp.get_json()
    export = client.post("/export/pdf", json=payload)
    assert export.status_code == 200
    assert export.headers["Content-Type"].startswith("application/pdf")
    assert export.data.startswith(b"%PDF")
    assert b"%%EOF" in export.data


def test_export_csv(client):
    resp = upload(client, make_wav(), make_wav(silent=True))
    assert resp.status_code == 200
    payload = resp.get_json()
    export = client.post("/export/csv", json=payload)
    assert export.status_code == 200
    text = export.data.decode("utf-8-sig")
    assert "Filename" in text
    assert "Integrated Loudness (LUFS)" in text
    assert "True Peak (dBTP)" in text
    assert len(text.strip().splitlines()) == 3


def test_export_pdf_invalid_payload(client):
    for payload in ({}, {"results": []}, {"results": "nope"}):
        resp = client.post("/export/pdf", json=payload)
        assert resp.status_code == 400


def test_export_csv_skips_errors(client):
    good = make_wav()
    bad = io.BytesIO(b"not audio" * 50)
    resp = upload(client, good, bad)
    payload = resp.get_json()
    export = client.post("/export/csv", json=payload)
    assert len(export.data.decode("utf-8-sig").strip().splitlines()) == 2


def test_rate_limit_enforced(tmp_path):
    from truepeak.api import create_app

    application = create_app({
        "TESTING": True,
        "RATE_LIMIT_ENABLED": True,
        "RATE_LIMIT_MAX_CALLS": 2,
        "RATE_LIMIT_PER_SECONDS": 60,
        "TEMP_DIR": str(tmp_path / "temp2"),
    })
    with application.test_client() as app_client:
        for _ in range(2):
            resp = upload(app_client, make_wav())
            assert resp.status_code == 200
        resp = upload(app_client, make_wav())
        assert resp.status_code == 429
    application.config["TOKEN_STORE"].shutdown()


def test_rate_limit_disabled_allows_many(tmp_path):
    from truepeak.api import create_app

    application = create_app({
        "TESTING": True,
        "RATE_LIMIT_ENABLED": False,
        "RATE_LIMIT_MAX_CALLS": 2,
        "RATE_LIMIT_PER_SECONDS": 60,
        "TEMP_DIR": str(tmp_path / "temp3"),
    })
    with application.test_client() as app_client:
        for _ in range(5):
            resp = upload(app_client, make_wav())
            assert resp.status_code == 200
    application.config["TOKEN_STORE"].shutdown()
