PLATFORMS = [
    {
        "id": "spotify",
        "label": "Spotify",
        "target_lufs": -14.0,
        "max_tp_dbtp": -1.0,
    },
    {
        "id": "apple_music",
        "label": "Apple Music",
        "target_lufs": -16.0,
        "max_tp_dbtp": -1.0,
    },
    {
        "id": "youtube",
        "label": "YouTube",
        "target_lufs": -14.0,
        "max_tp_dbtp": -1.0,
    },
    {
        "id": "tidal",
        "label": "Tidal",
        "target_lufs": -14.0,
        "max_tp_dbtp": -1.0,
    },
    {
        "id": "amazon_music",
        "label": "Amazon Music",
        "target_lufs": -14.0,
        "max_tp_dbtp": -2.0,
    },
    {
        "id": "deezer",
        "label": "Deezer",
        "target_lufs": -15.0,
        "max_tp_dbtp": -1.0,
    },
    {
        "id": "soundcloud",
        "label": "SoundCloud",
        "target_lufs": -14.0,
        "max_tp_dbtp": -1.0,
    },
    {
        "id": "ebu_r128",
        "label": "EBU R128 (Broadcast)",
        "target_lufs": -23.0,
        "max_tp_dbtp": -1.0,
    },
    {
        "id": "atsc_a85",
        "label": "ATSC A/85 (US TV)",
        "target_lufs": -24.0,
        "max_tp_dbtp": -2.0,
    },
]


def build_verdicts(analysis):
    integrated = analysis.get("loudness_integrated_lufs")
    true_peak = analysis.get("true_peak_dbtp")
    verdicts = []
    for platform in PLATFORMS:
        playback_gain = None
        if integrated is not None:
            playback_gain = float(round(platform["target_lufs"] - integrated, 1))
        status = "na"
        if playback_gain is not None:
            if playback_gain > 1.0:
                status = "quiet"
            elif playback_gain < -1.0:
                status = "loud"
            else:
                status = "on_target"
        true_peak_ok = None
        if true_peak is not None:
            true_peak_ok = true_peak <= platform["max_tp_dbtp"]
        verdicts.append({
            "id": platform["id"],
            "label": platform["label"],
            "target_lufs": platform["target_lufs"],
            "max_tp_dbtp": platform["max_tp_dbtp"],
            "playback_gain_db": playback_gain,
            "status": status,
            "true_peak_ok": true_peak_ok,
        })
    return verdicts
