import csv
import io


def _format(value, decimals=2):
    if value is None:
        return ""
    return f"{value:.{decimals}f}"


def export_csv(results):
    buffer = io.StringIO()
    fieldnames = [
        "Filename",
        "Duration (s)",
        "Sample Rate (Hz)",
        "Channels",
        "Integrated Loudness (LUFS)",
        "Max Short-term (LUFS)",
        "Max Momentary (LUFS)",
        "LRA (LU)",
        "True Peak (dBTP)",
        "Sample Peak (dBFS)",
        "RMS (dB)",
        "PLR (dB)",
        "Crest Factor (dB)",
        "Phase Correlation",
        "Min Correlation (1s)",
        "L/R Balance (dB)",
        "DC Offset L",
        "DC Offset R",
        "Clipping Events",
        "Clipping Max Run (samples)",
        "Spotify Playback Gain (dB)",
        "Apple Music Playback Gain (dB)",
        "YouTube Playback Gain (dB)",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for result in results:
        if result.get("error"):
            continue
        analysis = result.get("analysis") or {}
        dc = analysis.get("dc_offset_per_channel") or []
        clipping = analysis.get("clipping")
        verdicts = {v.get("id"): v for v in (result.get("verdicts") or [])}
        row = {
            "Filename": result.get("filename", "Unknown"),
            "Duration (s)": _format(result.get("duration_s")),
            "Sample Rate (Hz)": result.get("sample_rate"),
            "Channels": result.get("channels"),
            "Integrated Loudness (LUFS)": _format(analysis.get("loudness_integrated_lufs")),
            "Max Short-term (LUFS)": _format(analysis.get("short_term_max_lufs")),
            "Max Momentary (LUFS)": _format(analysis.get("momentary_max_lufs")),
            "LRA (LU)": _format(analysis.get("lra_lu")),
            "True Peak (dBTP)": _format(analysis.get("true_peak_dbtp")),
            "Sample Peak (dBFS)": _format(analysis.get("sample_peak_dbfs")),
            "RMS (dB)": _format(analysis.get("rms_db")),
            "PLR (dB)": _format(analysis.get("plr_db")),
            "Crest Factor (dB)": _format(analysis.get("crest_factor_db")),
            "Phase Correlation": _format(analysis.get("phase_correlation")),
            "Min Correlation (1s)": _format(analysis.get("phase_correlation_min")),
            "L/R Balance (dB)": _format(analysis.get("lr_balance_db")),
            "DC Offset L": _format(dc[0], 5) if len(dc) > 0 else "",
            "DC Offset R": _format(dc[1], 5) if len(dc) > 1 else "",
            "Clipping Events": clipping.get("runs") if clipping else "",
            "Clipping Max Run (samples)": clipping.get("max_run_samples") if clipping else "",
            "Spotify Playback Gain (dB)": _format(
                verdicts.get("spotify", {}).get("playback_gain_db")
            ),
            "Apple Music Playback Gain (dB)": _format(
                verdicts.get("apple_music", {}).get("playback_gain_db")
            ),
            "YouTube Playback Gain (dB)": _format(
                verdicts.get("youtube", {}).get("playback_gain_db")
            ),
        }
        writer.writerow(row)
    raw = buffer.getvalue()
    return io.BytesIO(raw.encode("utf-8-sig"))
