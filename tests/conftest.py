import io
import math

import numpy as np
import pytest
import soundfile as sf


def make_wav(duration=2.0, amplitude=0.5, freq=997.0, sr=44100, channels=2, silent=False):
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    if silent:
        data = np.zeros((len(t), channels), dtype=np.float32)
    else:
        mono = amplitude * np.sin(2 * math.pi * freq * t)
        data = np.stack([mono] * channels, axis=1).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    buf.seek(0)
    return buf


@pytest.fixture()
def app(tmp_path):
    from truepeak.api import create_app

    application = create_app({
        "TESTING": True,
        "RATE_LIMIT_ENABLED": False,
        "TEMP_DIR": str(tmp_path / "temp"),
    })
    yield application
    application.config["TOKEN_STORE"].shutdown()


@pytest.fixture()
def client(app):
    with app.test_client() as app_client:
        yield app_client


def upload(client, *buffers, names=None):
    files = []
    for i, buf in enumerate(buffers):
        name = (names[i] if names else f"test_{i}.wav")
        buf.seek(0)
        files.append((buf, name))
    return client.post("/analyze", data={"file": files}, content_type="multipart/form-data")
