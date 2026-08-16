import io
import threading

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

PLOT_LOCK = threading.Lock()


def _png(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    buffer.seek(0)
    return buffer


def waveform_png(wave_min, wave_max, duration_s, title="Waveform"):
    x_max = duration_s if duration_s and duration_s > 0 else 1.0
    n = max(len(wave_min), 2)
    xs = np.linspace(0.0, x_max, n)
    with PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(9.5, 2.6))
        ax.fill_between(xs, wave_min, wave_max, color="#1f6feb", alpha=0.55)
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Amplitude")
        ax.set_ylim(-1.05, 1.05)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return _png(fig)


def timeline_png(
    t_momentary,
    momentary,
    t_short_term,
    short_term,
    integrated=None,
    title="Loudness over time (LUFS)",
):
    with PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(9.5, 3.2))
        if t_momentary and momentary:
            ax.plot(t_momentary, momentary, color="#58a6ff", linewidth=0.7, label="Momentary")
        if t_short_term and short_term:
            ax.plot(t_short_term, short_term, color="#f0b429", linewidth=1.1, label="Short-term")
        if integrated is not None:
            ax.axhline(integrated, color="#3fb950", linestyle="--", linewidth=1.2, label="Integrated")
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("LUFS")
        ax.invert_yaxis()
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=8)
        fig.tight_layout()
        return _png(fig)


def spectrum_png(freqs, db, title="Average spectrum (1/3 octave)"):
    with PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(9.5, 3.0))
        valid = [(f, d) for f, d in zip(freqs, db) if d is not None]
        if valid:
            fs, ds = zip(*valid)
            ax.semilogx(fs, ds, color="#d2a8ff", linewidth=1.6)
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("Level (dB)")
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        return _png(fig)


def bars_png(
    labels,
    values,
    title,
    ylabel,
    target=None,
    target_label=None,
    max_labels=24,
):
    with PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(9.5, 3.4))
        valid = [(i, v) for i, v in enumerate(values) if v is not None]
        if valid:
            idx, vals = zip(*valid)
            ax.bar([i for i in idx], list(vals), color="#1f6feb", alpha=0.85)
        if target is not None:
            ax.axhline(target, color="#f85149", linestyle="--", linewidth=1.3)
            ax.text(
                0.99,
                target,
                target_label or f"target {target:g}",
                transform=ax.get_yaxis_transform(),
                ha="right",
                va="bottom",
                fontsize=8,
                color="#f85149",
            )
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(
            [label[:14] for label in labels], rotation=40, ha="right", fontsize=7
        )
        ax.set_title(title, fontsize=11)
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        return _png(fig)
