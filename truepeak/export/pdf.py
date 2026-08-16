import io
from datetime import datetime

from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..viz import plots

MARGIN = 40
LINE_H = 16
TITLE_FONT = "Helvetica-Bold"


def _format(value, decimals=2):
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}"


def _label(metric):
    return {
        "sample_peak_dbfs": "Sample Peak",
        "true_peak_dbtp": "True Peak (dBTP)",
        "rms_db": "RMS",
        "loudness_integrated_lufs": "Integrated Loudness",
        "momentary_max_lufs": "Max Momentary Loudness",
        "short_term_max_lufs": "Max Short-term Loudness",
        "lra_lu": "Loudness Range (LRA)",
        "plr_db": "Peak-to-Loudness (PLR)",
        "crest_factor_db": "Crest Factor",
        "phase_correlation": "Phase Correlation",
        "phase_correlation_min": "Min Correlation (1s)",
        "lr_balance_db": "L/R Balance",
    }.get(metric, metric.replace("_", " ").capitalize())


class _PdfWriter:
    def __init__(self, buffer):
        self.p = canvas.Canvas(buffer, pagesize=letter)
        self.width, self.height = letter
        self.y = self.height - MARGIN

    def new_page(self):
        self.p.showPage()
        self.y = self.height - MARGIN

    def ensure(self, needed):
        if self.y - needed < MARGIN:
            self.new_page()

    def text(self, text, size=10, bold=False, color=None):
        self.ensure(LINE_H)
        self.p.setFont(TITLE_FONT if bold else "Helvetica", size)
        if color:
            self.p.setFillColor(color)
        self.p.drawString(MARGIN, self.y, text)
        if color:
            self.p.setFillColor((0, 0, 0))
        self.y -= LINE_H

    def image(self, buffer, height):
        self.ensure(height + 12)
        self.y -= height
        try:
            img = ImageReader(buffer)
            self.p.drawImage(img, MARGIN, self.y, width=self.width - 2 * MARGIN, height=height)
        except Exception:
            self.p.setFont("Helvetica", 9)
            self.p.drawString(MARGIN, self.y + height / 2, "[Image unavailable]")
        self.y -= 12

    def save(self):
        self.p.save()


def export_pdf(results, album=None):
    buffer = io.BytesIO()
    w = _PdfWriter(buffer)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    w.text("TRUEPEAK - Mastering QC Report", 18, bold=True)
    w.text(f"Generated: {now}")
    w.text(f"Tracks analyzed: {len(results)}")
    w.text("")

    valid = [r for r in results if not r.get("error")]
    if valid:
        lufs = [r["analysis"].get("loudness_integrated_lufs") for r in valid]
        tp = [r["analysis"].get("true_peak_dbtp") for r in valid]
        lufs_ok = [v for v in lufs if v is not None]
        tp_ok = [v for v in tp if v is not None]
        w.text(
            "Album summary:"
            f" integrated {_format(min(lufs_ok) if lufs_ok else None)} to"
            f" {_format(max(lufs_ok) if lufs_ok else None)} LUFS"
            f" (spread {_format((max(lufs_ok) - min(lufs_ok)) if lufs_ok and len(lufs_ok) > 1 else None)} LU)",
            size=10,
        )
        w.text(
            f"Max true peak: {_format(max(tp_ok) if tp_ok else None)} dBTP",
            size=10,
        )
        if len(valid) > 1:
            names = [r["filename"] for r in valid]
            w.ensure(340)
            w.image(
                plots.bars_png(
                    names,
                    lufs,
                    "Integrated loudness by track (LUFS)",
                    "LUFS",
                    target=-14.0,
                    target_label="-14 LUFS (Spotify)",
                ),
                230,
            )
            w.image(
                plots.bars_png(
                    names,
                    tp,
                    "True peak by track (dBTP)",
                    "dBTP",
                    target=-1.0,
                    target_label="-1 dBTP",
                ),
                230,
            )

    w.text("")
    for result in results:
        filename = result.get("filename", "Unknown")
        if result.get("error"):
            w.text(f"File: {filename}", 13, bold=True)
            w.text(f"Error: {str(result['error'])[:120]}")
            continue
        w.ensure(LINE_H * 3 + 340)
        w.text(f"File: {filename}", 13, bold=True)
        analysis = result.get("analysis") or {}
        meta = (
            f"Duration: {_format(result.get('duration_s'))} s | "
            f"Sample rate: {result.get('sample_rate')} Hz | "
            f"Channels: {result.get('channels')}"
        )
        w.text(meta, size=9)

        rows = [
            ("sample_peak_dbfs", "dBFS"),
            ("true_peak_dbtp", "dBTP"),
            ("rms_db", "dB"),
            ("loudness_integrated_lufs", "LUFS"),
            ("momentary_max_lufs", "LUFS"),
            ("short_term_max_lufs", "LUFS"),
            ("lra_lu", "LU"),
            ("plr_db", "dB"),
            ("crest_factor_db", "dB"),
            ("phase_correlation", ""),
            ("phase_correlation_min", ""),
            ("lr_balance_db", "dB"),
        ]
        for metric, unit in rows:
            value = analysis.get(metric)
            text = f"{_label(metric)}: {_format(value)} {unit}".rstrip()
            w.text(text, size=9)

        clipping = analysis.get("clipping")
        if clipping:
            w.text(
                f"Clipping: {clipping.get('runs', 0)} events, "
                f"max run {clipping.get('max_run_samples', 0)} samples",
                size=9,
            )
        else:
            w.text("Clipping: none detected", size=9)

        verdicts = result.get("verdicts") or []
        if verdicts:
            w.ensure(LINE_H * (len(verdicts) + 2))
            w.text("Platform readiness:", 11, bold=True)
            for v in verdicts:
                tp_state = "OK" if v.get("true_peak_ok") else "EXCEEDS"
                gain = v.get("playback_gain_db")
                if gain is None:
                    gain_text = "n/a"
                elif gain > 0:
                    gain_text = f"+{gain:g} dB boost"
                else:
                    gain_text = f"{gain:g} dB cut"
                w.text(
                    f"  {v.get('label')}: target {v.get('target_lufs'):g} LUFS | "
                    f"playback {gain_text} | true peak {tp_state}",
                    size=9,
                )

        timeline = result.get("timeline") or {}
        spectrum = result.get("spectrum")
        waveform = result.get("waveform") or {}
        w.ensure(300)
        w.image(
            plots.waveform_png(
                waveform.get("min") or [],
                waveform.get("max") or [],
                result.get("duration_s"),
            ),
            200,
        )
        w.image(
            plots.timeline_png(
                timeline.get("t_momentary") or [],
                timeline.get("momentary") or [],
                timeline.get("t_short_term") or [],
                timeline.get("short_term") or [],
                analysis.get("loudness_integrated_lufs"),
            ),
            210,
        )
        if spectrum:
            w.ensure(240)
            w.image(
                plots.spectrum_png(spectrum.get("freqs") or [], spectrum.get("db") or []),
                200,
            )

    w.save()
    buffer.seek(0)
    return buffer
