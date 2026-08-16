import os
import io
import uuid
import time
import logging
import base64
import threading
import traceback
from collections import defaultdict
from functools import wraps

from flask import Flask, request, render_template, jsonify, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import numpy as np
import pandas as pd
import librosa
import pyloudnorm as pyln

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa.display

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'temp'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB limit
app.config['RATE_LIMIT_ENABLED'] = True

ALLOWED_EXTENSIONS = {'wav', 'mp3'}

METRICS = [
    "true_peak_dbfs",
    "rms_db",
    "loudness_integrated",
    "max_momentary_loudness",
    "max_short_term_loudness"
]

# Flask dev server is threaded: pyplot global state needs a lock
PLOT_LOCK = threading.Lock()


class RateLimiter:
    def __init__(self, max_calls, per_seconds):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.calls = defaultdict(list)
        self._lock = threading.Lock()

    def __call__(self, func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if not app.config.get('RATE_LIMIT_ENABLED', True):
                return func(*args, **kwargs)
            ip = request.remote_addr or 'unknown'
            now = time.time()
            with self._lock:
                self.calls[ip] = [call for call in self.calls[ip] if call > now - self.per_seconds]
                if len(self.calls[ip]) >= self.max_calls:
                    return jsonify({"error": "Too many requests"}), 429
                self.calls[ip].append(now)
            return func(*args, **kwargs)

        return wrapped


rate_limiter = RateLimiter(max_calls=10, per_seconds=60)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def sanitize_metrics(analysis):
    """Convert numpy types to native floats; NaN/±inf become None (valid JSON null)."""
    cleaned = {}
    for key, value in analysis.items():
        if value is None:
            cleaned[key] = None
            continue
        if isinstance(value, (np.floating, np.integer)):
            value = float(value)
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            cleaned[key] = None
        else:
            cleaned[key] = value
    return cleaned


def truncate_text(text, max_len):
    text = str(text)
    return text if len(text) <= max_len else text[:max_len - 3] + "..."


def format_metric(value):
    if value is None:
        return "N/A"
    try:
        return f"{value:.2f}"
    except (TypeError, ValueError):
        return str(value)


def fig_to_base64(fig):
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', bbox_inches='tight')
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
@rate_limiter
def analyze():
    logger.info("POST /analyze received")
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400

        files = request.files.getlist('file')
        if not files or files[0].filename == '':
            return jsonify({"error": "No selected file"}), 400

        for file in files:
            if not file or not allowed_file(file.filename):
                logger.error(f"Invalid file type: {file.filename}")
                return jsonify({"error": f"Invalid file type: {file.filename}"}), 400

        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        filenames = []
        try:
            for file in files:
                original = secure_filename(file.filename) or "audio"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4().hex}_{original}")
                file.save(filepath)
                filenames.append(filepath)
        except Exception:
            logger.exception("Error saving uploaded files")
            cleanup_files(filenames)
            return jsonify({"error": "Could not save uploaded files"}), 500

        try:
            results = process_audio_files(filenames)
            logger.info("Analysis complete")
            return jsonify(results), 200
        except Exception:
            logger.exception("Error processing files")
            return jsonify({"error": "Error processing files"}), 500
    except Exception:
        logger.exception("Unexpected error in /analyze")
        return jsonify({"error": "An unexpected error occurred. Please try again."}), 500


@app.route('/export/pdf', methods=['POST'])
@rate_limiter
def export_pdf_route():
    logger.info("POST /export/pdf received")
    try:
        payload = request.get_json(silent=True) or {}
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return jsonify({"error": "Invalid export data"}), 400
        comparison_imgs = payload.get("comparison_imgs") or None
        pdf_buffer = export_pdf(results, comparison_imgs)
        return send_file(pdf_buffer, mimetype='application/pdf', as_attachment=True,
                         download_name='audio_analysis.pdf')
    except Exception:
        logger.exception("Error generating PDF")
        return jsonify({"error": "Error generating PDF"}), 500


@app.route('/export/csv', methods=['POST'])
@rate_limiter
def export_csv_route():
    logger.info("POST /export/csv received")
    try:
        payload = request.get_json(silent=True) or {}
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return jsonify({"error": "Invalid export data"}), 400
        csv_buffer = export_csv(results)
        return send_file(csv_buffer, mimetype='text/csv', as_attachment=True,
                         download_name='audio_analysis.csv')
    except Exception:
        logger.exception("Error generating CSV")
        return jsonify({"error": "Error generating CSV"}), 500


def process_audio_files(filenames):
    logger.info(f"Processing {len(filenames)} files")
    results = []

    try:
        for filepath in filenames:
            try:
                analysis_results, waveform_img, spectrogram_img = analyze_audio(filepath)
                results.append({
                    "filename": os.path.basename(filepath),
                    "analysis": analysis_results,
                    "waveform_img": waveform_img,
                    "spectrogram_img": spectrogram_img
                })
            except Exception as e:
                logger.exception(f"Error processing file {filepath}")
                results.append({
                    "filename": os.path.basename(filepath),
                    "error": str(e)
                })

        valid_results = [r for r in results if "error" not in r]
        comparison_imgs = generate_comparison_graphs(valid_results) if len(valid_results) > 1 else None

        return {
            "results": results,
            "comparison_imgs": comparison_imgs
        }
    finally:
        cleanup_files(filenames)


def analyze_audio(file_path):
    logger.info(f"Analyzing audio file: {file_path}")
    try:
        audio_data, rate = librosa.load(file_path, sr=None)

        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)

        true_peak = np.max(np.abs(audio_data))
        rms_value = np.sqrt(np.mean(np.square(audio_data)))
        with np.errstate(divide='ignore', invalid='ignore'):
            true_peak_dbfs = 20 * np.log10(true_peak)
            rms_db = 20 * np.log10(rms_value)

        metrics = {
            "true_peak_dbfs": true_peak_dbfs,
            "rms_db": rms_db,
            "loudness_integrated": None,
            "max_momentary_loudness": None,
            "max_short_term_loudness": None
        }

        # Loudness requires blocks of ~400ms/3s; files shorter than that
        # raise from pyloudnorm, so these metrics are optional.
        try:
            meter = pyln.Meter(rate)
            metrics["loudness_integrated"] = meter.integrated_loudness(audio_data)

            block_size_momentary = int(0.4 * rate)
            momentary_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_momentary])
                                  for i in range(0, len(audio_data), block_size_momentary)
                                  if len(audio_data[i:i + block_size_momentary]) == block_size_momentary]
            metrics["max_momentary_loudness"] = np.max(momentary_loudness) if momentary_loudness else float('nan')

            block_size_short_term = int(3 * rate)
            short_term_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_short_term])
                                   for i in range(0, len(audio_data), block_size_short_term)
                                   if len(audio_data[i:i + block_size_short_term]) == block_size_short_term]
            metrics["max_short_term_loudness"] = np.max(short_term_loudness) if short_term_loudness else float('nan')
        except ValueError:
            logger.warning(f"Audio too short for loudness analysis: {file_path}")
        except Exception as e:
            logger.warning(f"Loudness analysis failed for {file_path}: {e}")

        metrics = sanitize_metrics(metrics)

        waveform_img = generate_waveform(audio_data, rate)
        spectrogram_img = generate_spectrogram(audio_data, rate)

        logger.info(f"Analysis complete for: {file_path}")
        return metrics, waveform_img, spectrogram_img
    except Exception:
        logger.exception(f"Error analyzing audio: {file_path}")
        raise


def generate_waveform(audio_data, rate):
    with PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(10, 4))
        librosa.display.waveshow(audio_data, sr=rate, ax=ax)
        ax.set_title('Waveform')
        ax.set_xlabel('Time')
        ax.set_ylabel('Amplitude')
        fig.tight_layout()
        return fig_to_base64(fig)


def generate_spectrogram(audio_data, rate):
    with PLOT_LOCK:
        fig, ax = plt.subplots(figsize=(10, 4))
        S = librosa.feature.melspectrogram(y=audio_data, sr=rate)
        S_dB = librosa.power_to_db(S, ref=np.max)
        img = librosa.display.specshow(S_dB, sr=rate, x_axis='time', y_axis='mel', ax=ax)
        fig.colorbar(img, ax=ax, format='%+2.0f dB')
        ax.set_title('Mel-frequency spectrogram')
        fig.tight_layout()
        return fig_to_base64(fig)


def generate_comparison_graphs(results):
    comparison_imgs = {}

    for metric in METRICS:
        valid = [
            (r["filename"], r["analysis"][metric])
            for r in results
            if metric in r.get("analysis", {}) and r["analysis"][metric] is not None
        ]
        with PLOT_LOCK:
            fig, ax = plt.subplots(figsize=(10, 6))
            if valid:
                names = [v[0] for v in valid]
                values = [v[1] for v in valid]
                ax.bar(range(len(values)), values)
                ax.set_xticks(range(len(values)))
                ax.set_xticklabels([truncate_text(n, 20) for n in names], rotation=45, ha='right')
            else:
                ax.text(0.5, 0.5, "No valid data for this metric",
                        ha='center', va='center', transform=ax.transAxes)
                ax.set_xticks([])
            ax.set_title(f'Comparison of {metric.replace("_", " ").capitalize()}')
            ax.set_xlabel('Tracks')
            ax.set_ylabel(metric.replace('_', ' ').capitalize())
            fig.tight_layout()
            comparison_imgs[metric] = fig_to_base64(fig)

    return comparison_imgs


def export_pdf(results, comparison_imgs):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 40
    line_h = 18
    img_width = width - 2 * margin
    img_height = 200
    comp_height = 300

    y = height - margin

    def new_page_if_needed(needed):
        nonlocal y
        if y - needed < margin:
            p.showPage()
            y = height - margin

    def draw_text(text, size=11):
        nonlocal y
        new_page_if_needed(line_h)
        p.setFont("Helvetica", size)
        p.drawString(margin, y, text)
        y -= line_h

    def draw_image_from_base64(b64data, w, h):
        nonlocal y
        new_page_if_needed(h + 10)
        y -= h
        try:
            img = ImageReader(io.BytesIO(base64.b64decode(b64data)))
            p.drawImage(img, margin, y, width=w, height=h)
        except Exception:
            logger.exception("Could not embed image in PDF")
            p.setFont("Helvetica", 10)
            p.drawString(margin, y + h / 2, "[Image unavailable]")
        y -= 10

    for result in results:
        filename = truncate_text(result.get("filename", "Unknown"), 80)

        if result.get("error"):
            draw_text(f"File: {filename}", size=13)
            draw_text(f"Error: {truncate_text(str(result['error']), 80)}")
            continue

        block_height = line_h + len(METRICS) * line_h + 2 * (img_height + 10) + 10
        new_page_if_needed(block_height)

        draw_text(f"File: {filename}", size=13)
        analysis = result.get("analysis") or {}
        for metric in METRICS:
            label = metric.replace("_", " ").capitalize()
            draw_text(f"{label}: {format_metric(analysis.get(metric))}")
        draw_image_from_base64(result.get("waveform_img", ""), img_width, img_height)
        draw_image_from_base64(result.get("spectrogram_img", ""), img_width, img_height)

    if comparison_imgs:
        p.showPage()
        y = height - margin
        draw_text("Comparison Graphs", size=15)
        for metric, img_data in comparison_imgs.items():
            needed = line_h + comp_height + 10
            new_page_if_needed(needed)
            draw_text(metric.replace("_", " ").capitalize(), size=12)
            draw_image_from_base64(img_data, img_width, comp_height)

    p.save()
    buffer.seek(0)
    return buffer


def export_csv(results):
    buffer = io.BytesIO()
    data = []
    for result in results:
        if result.get("error"):
            continue
        analysis = result.get("analysis") or {}
        data.append({
            "Filename": result.get("filename", "Unknown"),
            "True Peak (dBFS)": analysis.get("true_peak_dbfs"),
            "RMS (dB)": analysis.get("rms_db"),
            "Loudness Integrated (LUFS)": analysis.get("loudness_integrated"),
            "Max Loudness Momentary (LUFS)": analysis.get("max_momentary_loudness"),
            "Max Loudness Short Term (LUFS)": analysis.get("max_short_term_loudness")
        })

    df = pd.DataFrame(data)
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    return buffer


def cleanup_files(filenames):
    for filename in filenames:
        try:
            if os.path.exists(filename):
                os.remove(filename)
                logger.info(f"File deleted: {filename}")
        except Exception:
            logger.exception(f"Error deleting file {filename}")


@app.errorhandler(413)
def file_too_large(error):
    return jsonify({"error": "File too large. Max file size exceeded."}), 413


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    logger.exception("Unhandled exception")
    return jsonify({"error": "Server error. Please try again later."}), 500


if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    logger.info("Starting Flask server")
    app.run(debug=True)