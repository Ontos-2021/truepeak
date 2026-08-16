import io
import json

import soundfile as sf

from tests.conftest import make_wav, upload

SR = 44100


def write_wav(data, sr):
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    buf.seek(0)
    return buf


def test_file_provider_streams_blocks():
    from truepeak.analysis.dsp import FileProvider

    buf = make_wav(duration=1.0)
    path = _save_tmp(buf)
    try:
        provider = FileProvider(path)
        sr, nch, frames = provider.info()
        assert sr == SR
        assert nch == 2
        total = sum(len(b) for b in provider.blocks(4096))
        assert total == frames
    finally:
        _delete_tmp(path)


def _save_tmp(buf):
    import os
    import uuid

    os.makedirs("temp", exist_ok=True)
    path = os.path.join("temp", f"test_{uuid.uuid4().hex}.wav")
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return path


def _delete_tmp(path):
    import os

    try:
        os.remove(path)
    except OSError:
        pass


def test_compact_result_json_serializable(client):
    resp = upload(client, make_wav(duration=1.0))
    payload = resp.get_json()
    raw = json.dumps(payload)
    assert "Infinity" not in raw
    assert "NaN" not in raw
