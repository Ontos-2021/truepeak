import io
import json
import math
import os
import uuid

import numpy as np
import pytest
import soundfile as sf

import app as app_module

SR = 44100


@pytest.fixture(scope="session", autouse=True)
def ensure_temp_dir():
    os.makedirs(app_module.app.config['UPLOAD_FOLDER'], exist_ok=True)
    yield
    for f in os.listdir(app_module.app.config['UPLOAD_FOLDER']):
        try:
            os.remove(os.path.join(app_module.app.config['UPLOAD_FOLDER'], f))
        except OSError:
            pass


def make_wav(duration=2.0, amplitude=0.5, freq=440.0, silent=False):
    t = np.linspace(0, duration, int(SR * duration), endpoint=False)
    if silent:
        data = np.zeros_like(t, dtype=np.float32)
    else:
        data = (amplitude * np.sin(2 * math.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, data, SR, format='WAV')
    buf.seek(0)
    return buf


def strict_json_loads(raw):
    """Parse JSON rejecting non-standard NaN/Infinity literals."""
    def raise_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")
    return json.loads(raw, parse_constant=raise_constant)


def upload(client, *buffers, names=None):
    files = []
    for i, buf in enumerate(buffers):
        name = (names[i] if names else f"test_{i}.wav")
        buf.seek(0)
        files.append((buf, name))
    return client.post('/analyze', data={'file': files}, content_type='multipart/form-data')


def test_index_renders(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert b'Audio Analysis Tool' in resp.data


def test_analyze_single_file(client):
    resp = upload(client, make_wav())
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['results']) == 1
    result = data['results'][0]
    assert 'error' not in result
    analysis = result['analysis']
    for metric in app_module.METRICS:
        assert metric in analysis
        assert isinstance(analysis[metric], (float, type(None)))
    assert isinstance(result['waveform_img'], str)
    assert isinstance(result['spectrogram_img'], str)
    assert data['comparison_imgs'] is None
    strict_json_loads(resp.data.decode('utf-8'))


def test_analyze_multiple_files_comparison(client):
    resp = upload(client, make_wav(freq=440.0), make_wav(freq=880.0, amplitude=0.8))
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data['results']) == 2
    assert data['comparison_imgs'] is not None
    assert set(data['comparison_imgs'].keys()) == set(app_module.METRICS)


def test_analyze_silent_file(client):
    resp = upload(client, make_wav(silent=True))
    assert resp.status_code == 200
    data = resp.get_json()
    result = data['results'][0]
    assert result.get('error') is None or 'analysis' in result
    strict_json_loads(resp.data.decode('utf-8'))


def test_analyze_short_file(client):
    resp = upload(client, make_wav(duration=0.2))
    assert resp.status_code == 200
    data = resp.get_json()
    result = data['results'][0]
    assert 'error' not in result
    analysis = result['analysis']
    assert analysis['true_peak_dbfs'] is not None
    assert analysis['loudness_integrated'] is None
    assert analysis['max_momentary_loudness'] is None
    assert analysis['max_short_term_loudness'] is None
    strict_json_loads(resp.data.decode('utf-8'))


def test_analyze_corrupted_file(client):
    buf = io.BytesIO(b'this is not a wav file at all' * 100)
    resp = upload(client, buf)
    assert resp.status_code == 200
    data = resp.get_json()
    result = data['results'][0]
    assert 'error' in result


def test_analyze_invalid_extension(client):
    buf = io.BytesIO(b'garbage')
    resp = upload(client, buf, names=['not_audio.txt'])
    assert resp.status_code == 400
    assert 'Invalid file type' in resp.get_json()['error']


def test_analyze_no_files(client):
    resp = client.post('/analyze', data={}, content_type='multipart/form-data')
    assert resp.status_code == 400


def test_export_pdf(client):
    resp = upload(client, make_wav(), make_wav(freq=300.0))
    assert resp.status_code == 200
    payload = resp.get_json()
    export = client.post('/export/pdf', json={
        'results': payload['results'],
        'comparison_imgs': payload['comparison_imgs']
    })
    assert export.status_code == 200
    assert export.headers['Content-Type'].startswith('application/pdf')
    assert export.data.startswith(b'%PDF')
    assert b'%%EOF' in export.data


def test_export_csv(client):
    resp = upload(client, make_wav(), make_wav(silent=True))
    assert resp.status_code == 200
    payload = resp.get_json()
    export = client.post('/export/csv', json={'results': payload['results']})
    assert export.status_code == 200
    assert export.headers['Content-Type'].startswith('text/csv')
    text = export.data.decode('utf-8')
    assert 'Filename' in text
    assert 'True Peak (dBFS)' in text
    assert 'Max Loudness Short Term (LUFS)' in text


def test_export_csv_skips_errors(client):
    good = make_wav()
    bad = io.BytesIO(b'not audio' * 50)
    resp = upload(client, good, bad)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert any('error' in r for r in payload['results'])
    export = client.post('/export/csv', json={'results': payload['results']})
    assert export.status_code == 200
    assert export.data.decode('utf-8').count('Filename') == 1


def test_export_pdf_invalid_payload(client):
    export = client.post('/export/pdf', json={'results': []})
    assert export.status_code == 400
    export = client.post('/export/pdf', json={})
    assert export.status_code == 400
    export = client.post('/export/pdf', data='not json', content_type='application/json')
    assert export.status_code == 400


def test_sanitize_metrics():
    from app import sanitize_metrics
    assert sanitize_metrics({'a': np.float32(1.5), 'b': float('nan'), 'c': float('-inf')}) == {
        'a': 1.5, 'b': None, 'c': None
    }
    assert sanitize_metrics({'d': np.float64(2.0)}) == {'d': 2.0}


def test_temp_files_cleaned_after_analyze(client):
    before = set(os.listdir(app_module.app.config['UPLOAD_FOLDER']))
    upload(client, make_wav())
    after = set(os.listdir(app_module.app.config['UPLOAD_FOLDER']))
    assert after == before