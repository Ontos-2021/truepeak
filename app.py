import os
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
import librosa
import numpy as np
import pyloudnorm as pyln
import pandas as pd
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa.display
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from celery import Celery
import base64
from functools import wraps
import time
from collections import defaultdict

# Configuración de la aplicación Flask y Celery
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'temp'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB limit
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'


def make_celery(app):
    celery = Celery(
        app.import_name,
        broker=app.config['CELERY_BROKER_URL'],
        backend=app.config['CELERY_RESULT_BACKEND']
    )
    celery.conf.update(app.config)
    return celery


celery = make_celery(app)

ALLOWED_EXTENSIONS = {'wav', 'mp3'}


# Implementación simple de Rate Limiting
class RateLimiter:
    def __init__(self, max_calls, per_seconds):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.calls = defaultdict(list)

    def __call__(self, func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            now = time.time()
            self.calls[request.remote_addr] = [call for call in self.calls[request.remote_addr] if
                                               call > now - self.per_seconds]
            if len(self.calls[request.remote_addr]) >= self.max_calls:
                return jsonify({"error": "Too many requests"}), 429
            self.calls[request.remote_addr].append(now)
            return func(*args, **kwargs)

        return wrapped


rate_limiter = RateLimiter(max_calls=10, per_seconds=60)  # 10 calls per minute


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/', methods=['GET', 'POST'])
@rate_limiter
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        files = request.files.getlist('file')
        if not files or files[0].filename == '':
            return jsonify({"error": "No selected file"}), 400

        filenames = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                filenames.append(filepath)
            else:
                return jsonify({"error": "Invalid file type"}), 400

        task = process_audio_files.delay(filenames)
        return jsonify({"task_id": task.id}), 202

    return render_template('index.html')


# Add a try/except block for audio analysis
@celery.task(bind=True)
def process_audio_files(self, filenames):
    results = []
    total_files = len(filenames)
    
    try:
        for index, filepath in enumerate(filenames, start=1):
            self.update_state(state='PROGRESS',
                              meta={'current': index, 'total': total_files})
            try:
                analysis_results, waveform_img, spectrogram_img = analyze_audio(filepath)
                results.append({
                    "filename": os.path.basename(filepath),
                    "analysis": analysis_results,
                    "waveform_img": waveform_img,
                    "spectrogram_img": spectrogram_img
                })
            except Exception as e:
                app.logger.error(f"Error processing file {filepath}: {e}")
                results.append({
                    "filename": os.path.basename(filepath),
                    "error": str(e)
                })

        # Only generate comparisons for files that were successfully analyzed
        valid_results = [r for r in results if "error" not in r]
        comparison_imgs = generate_comparison_graphs(valid_results) if len(valid_results) > 1 else None
        pdf_buffer = export_pdf(results, comparison_imgs)
        csv_buffer = export_csv(results)

        return {
            "results": results,
            "comparison_imgs": comparison_imgs,
            "pdf": base64.b64encode(pdf_buffer.getvalue()).decode('utf-8'),
            "csv": base64.b64encode(csv_buffer.getvalue()).decode('utf-8')
        }
    finally:
        # Always clean up files regardless of success or failure
        cleanup_files(filenames)


@app.route('/status/<task_id>')
def task_status(task_id):
    task = process_audio_files.AsyncResult(task_id)
    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'current': 0,
            'total': 1,
            'status': 'Pending...'
        }
    elif task.state != 'FAILURE':
        response = {
            'state': task.state,
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 1),
            'status': task.info.get('status', '')
        }
        if task.state == 'SUCCESS':
            response['result'] = task.result
    else:
        response = {
            'state': task.state,
            'current': 1,
            'total': 1,
            'status': str(task.info)
        }
    return jsonify(response)


def analyze_audio(file_path):
    audio_data, rate = librosa.load(file_path, sr=None)
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)

    true_peak = np.max(np.abs(audio_data))
    true_peak_dbfs = 20 * np.log10(true_peak)

    rms_value = np.sqrt(np.mean(np.square(audio_data)))
    rms_db = 20 * np.log10(rms_value)

    meter = pyln.Meter(rate)
    loudness_integrated = meter.integrated_loudness(audio_data)

    block_size_momentary = int(0.4 * rate)
    momentary_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_momentary])
                          for i in range(0, len(audio_data), block_size_momentary)
                          if len(audio_data[i:i + block_size_momentary]) == block_size_momentary]
    max_momentary_loudness = np.max(momentary_loudness) if momentary_loudness else float('nan')

    block_size_short_term = int(3 * rate)
    short_term_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_short_term])
                           for i in range(0, len(audio_data), block_size_short_term)
                           if len(audio_data[i:i + block_size_short_term]) == block_size_short_term]
    max_short_term_loudness = np.max(short_term_loudness) if short_term_loudness else float('nan')

    # Generar forma de onda
    plt.figure(figsize=(10, 4))
    librosa.display.waveshow(audio_data, sr=rate)
    plt.title('Waveform')
    plt.xlabel('Time')
    plt.ylabel('Amplitude')
    waveform_buffer = io.BytesIO()
    plt.savefig(waveform_buffer, format='png')
    plt.close()
    waveform_buffer.seek(0)
    waveform_img = base64.b64encode(waveform_buffer.getvalue()).decode('utf-8')

    # Generar espectrograma
    plt.figure(figsize=(10, 4))
    S = librosa.feature.melspectrogram(y=audio_data, sr=rate)
    S_dB = librosa.power_to_db(S, ref=np.max)
    librosa.display.specshow(S_dB, sr=rate, x_axis='time', y_axis='mel')
    plt.colorbar(format='%+2.0f dB')
    plt.title('Mel-frequency spectrogram')
    spectrogram_buffer = io.BytesIO()
    plt.savefig(spectrogram_buffer, format='png')
    plt.close()
    spectrogram_buffer.seek(0)
    spectrogram_img = base64.b64encode(spectrogram_buffer.getvalue()).decode('utf-8')

    return {
               "true_peak_dbfs": true_peak_dbfs,
               "rms_db": rms_db,
               "loudness_integrated": loudness_integrated,
               "max_momentary_loudness": max_momentary_loudness,
               "max_short_term_loudness": max_short_term_loudness
           }, waveform_img, spectrogram_img


def generate_comparison_graphs(results):
    metrics = ["true_peak_dbfs", "rms_db", "loudness_integrated", "max_momentary_loudness", "max_short_term_loudness"]
    comparison_imgs = {}

    for metric in metrics:
        plt.figure(figsize=(10, 6))
        values = [result["analysis"][metric] for result in results]
        plt.bar(range(len(values)), values)
        plt.title(f'Comparison of {metric.replace("_", " ").capitalize()}')
        plt.xlabel('Tracks')
        plt.ylabel(metric.replace('_', ' ').capitalize())
        plt.xticks(range(len(values)), [result["filename"] for result in results], rotation=45, ha='right')
        plt.tight_layout()

        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png')
        plt.close()
        img_buffer.seek(0)
        comparison_imgs[metric] = base64.b64encode(img_buffer.getvalue()).decode('utf-8')

    return comparison_imgs


def export_pdf(results, comparison_imgs):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica", 12)
    y = height - 40

    for result in results:
        p.drawString(30, y, f'File: {result["filename"]}')
        y -= 20
        for metric, value in result["analysis"].items():
            p.drawString(30, y, f'{metric.replace("_", " ").capitalize()}: {value:.2f}')
            y -= 20

        p.drawImage(io.BytesIO(base64.b64decode(result["waveform_img"])), 30, y - 200, width=500, height=200)
        y -= 220
        p.drawImage(io.BytesIO(base64.b64decode(result["spectrogram_img"])), 30, y - 200, width=500, height=200)
        y -= 220

        if y < 100:
            p.showPage()
            y = height - 40

    if comparison_imgs:
        p.showPage()
        y = height - 40
        p.drawString(30, y, 'Comparison Graphs')
        y -= 40
        for metric, img_data in comparison_imgs.items():
            p.drawString(30, y, f'{metric.replace("_", " ").capitalize()}')
            y -= 20
            p.drawImage(io.BytesIO(base64.b64decode(img_data)), 30, y - 300, width=500, height=300)
            y -= 320
            if y < 100:
                p.showPage()
                y = height - 40

    p.save()
    buffer.seek(0)
    return buffer


def export_csv(results):
    buffer = io.StringIO()
    data = []
    for result in results:
        row = {
            "Filename": result["filename"],
            "True Peak (dBFS)": result["analysis"]["true_peak_dbfs"],
            "RMS (dB)": result["analysis"]["rms_db"],
            "Loudness Integrated (LUFS)": result["analysis"]["loudness_integrated"],
            "Max Loudness Momentary (LUFS)": result["analysis"]["max_momentary_loudness"],
            "Max Loudness Short Term (LUFS)": result["analysis"]["max_short_term_loudness"]
        }
        data.append(row)

    df = pd.DataFrame(data)
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    return buffer


def cleanup_files(filenames):
    for filename in filenames:
        try:
            os.remove(filename)
        except Exception as e:
            app.logger.error(f"Error deleting file {filename}: {e}")


if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(debug=True)
