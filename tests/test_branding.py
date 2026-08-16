"""Tests for branded PDF reports (studio name + logo via env config)."""
import re
import zlib

from tests.conftest import make_wav, upload


def _ascii85_decode(data):
    """Decode Adobe ASCII85 (used by reportlab before FlateDecode)."""
    data = data.split(b"~>")[0].replace(b"\n", b"").replace(b"\r", b"")
    out = bytearray()
    group = bytearray()
    for ch in data:
        if ch == 122:  # 'z'
            if group:
                raise ValueError("z inside group")
            out += b"\x00\x00\x00\x00"
            continue
        if ch < 33 or ch > 117:
            continue
        group.append(ch)
        if len(group) == 5:
            n = 0
            for c in group:
                n = n * 85 + (c - 33)
            out += n.to_bytes(4, "big")
            group.clear()
    if group:
        pad = 5 - len(group)
        for _ in range(pad):
            group.append(117)
        n = 0
        for c in group:
            n = n * 85 + (c - 33)
        out += n.to_bytes(4, "big")[: 4 - pad]
    return bytes(out)


def _pdf_text(data):
    """Extract and concatenate decoded (ASCII85+Flate) content streams."""
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        payload = m.group(1)
        if b"~>" not in payload:
            continue
        try:
            decoded = _ascii85_decode(payload)
            chunks.append(zlib.decompress(decoded))
        except Exception:
            continue
    return b" ".join(chunks)


def _analyzed_result(client):
    resp = upload(client, make_wav())
    assert resp.status_code == 200
    return resp.get_json()["results"][0]


def test_export_pdf_default_title(client):
    result = _analyzed_result(client)
    resp = client.post("/export/pdf", json={"results": [result], "album": {}})
    assert resp.status_code == 200
    assert resp.data[:4] == b"%PDF"
    assert b"TRUEPEAK - Mastering QC Report" in _pdf_text(resp.data)


def test_export_pdf_with_brand_name(tmp_path):
    from truepeak.api import create_app

    application = create_app({
        "TESTING": True,
        "RATE_LIMIT_ENABLED": False,
        "TEMP_DIR": str(tmp_path / "temp"),
        "BRAND_NAME": "Estudio XYZ",
        "BRAND_LOGO": "",
    })
    with application.test_client() as app_client:
        result = _analyzed_result(app_client)
        resp = app_client.post("/export/pdf", json={"results": [result], "album": {}})
        assert resp.status_code == 200
        text = _pdf_text(resp.data)
        assert b"Estudio XYZ - Mastering QC Report" in text
        assert b"Powered by TruePeak" in text
    application.config["TOKEN_STORE"].shutdown()


def test_export_pdf_with_logo(tmp_path):
    import struct
    import zlib as z

    from truepeak.api import create_app

    # tiny 1x1 red PNG
    raw = b"".join([
        b"\x00\xff\x00\x00\xff\x00\x00\x00",
        b"\xff\x00\x00\xff\x00\x00",
    ])
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13) + b"IHDR" + ihdr
        + struct.pack(">I", z.crc32(b"IHDR" + ihdr) % (1 << 32))
        + struct.pack(">I", len(raw)) + b"IDAT" + raw
        + struct.pack(">I", z.crc32(b"IDAT" + raw) % (1 << 32))
        + struct.pack(">I", 0) + b"IEND"
        + struct.pack(">I", z.crc32(b"IEND") % (1 << 32))
    )
    logo = tmp_path / "logo.png"
    logo.write_bytes(png)

    application = create_app({
        "TESTING": True,
        "RATE_LIMIT_ENABLED": False,
        "TEMP_DIR": str(tmp_path / "temp2"),
        "BRAND_NAME": "Estudio XYZ",
        "BRAND_LOGO": str(logo),
    })
    with application.test_client() as app_client:
        result = _analyzed_result(app_client)
        resp = app_client.post("/export/pdf", json={"results": [result], "album": {}})
        assert resp.status_code == 200
        assert b"Estudio XYZ - Mastering QC Report" in _pdf_text(resp.data)
    application.config["TOKEN_STORE"].shutdown()


def test_export_pdf_missing_logo_does_not_crash(tmp_path):
    from truepeak.api import create_app

    application = create_app({
        "TESTING": True,
        "RATE_LIMIT_ENABLED": False,
        "TEMP_DIR": str(tmp_path / "temp3"),
        "BRAND_NAME": "Estudio XYZ",
        "BRAND_LOGO": str(tmp_path / "no_existe.png"),
    })
    with application.test_client() as app_client:
        result = _analyzed_result(app_client)
        resp = app_client.post("/export/pdf", json={"results": [result], "album": {}})
        assert resp.status_code == 200
    application.config["TOKEN_STORE"].shutdown()


def test_index_uses_brand_name(tmp_path):
    from truepeak.api import create_app

    application = create_app({
        "TESTING": True,
        "RATE_LIMIT_ENABLED": False,
        "TEMP_DIR": str(tmp_path / "temp4"),
        "BRAND_NAME": "Estudio XYZ",
        "BRAND_LOGO": "",
    })
    with application.test_client() as app_client:
        resp = app_client.get("/")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "<h1>Estudio XYZ</h1>" in html
    application.config["TOKEN_STORE"].shutdown()