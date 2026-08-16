import os
from flask import Flask, request, render_template, jsonify, make_response
from werkzeug.utils import secure_filename
import librosa
import numpy as np
import pyloudnorm as pyln
import pandas as pd
import matplotlib
import traceback
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import librosa.display
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import base64
from functools import wraps
import time
from collections import defaultdict
from reportlab.lib.utils import ImageReader

# Configuración de la aplicación Flask
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'temp'
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200 MB limit

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
        app.logger.info("POST request received")
        try:
            app.logger.info(f"Request files: {request.files}")
            if 'file' not in request.files:
                app.logger.error("No file part in request")
                return jsonify({"error": "No file part"}), 400
                
            files = request.files.getlist('file')
            app.logger.info(f"Number of files: {len(files)}")
            
            if not files or files[0].filename == '':
                app.logger.error("No selected file")
                return jsonify({"error": "No selected file"}), 400

            # Ensure the upload directory exists
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                app.logger.info(f"Creating upload folder: {app.config['UPLOAD_FOLDER']}")
                os.makedirs(app.config['UPLOAD_FOLDER'])

            filenames = []
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    app.logger.info(f"Saving file to: {filepath}")
                    try:
                        file.save(filepath)
                        filenames.append(filepath)
                        app.logger.info(f"File saved successfully: {filepath}")
                    except Exception as e:
                        app.logger.error(f"Error saving file {filename}: {str(e)}")
                        app.logger.error(traceback.format_exc())
                        return jsonify({"error": f"Could not save file {filename}: {str(e)}"}), 500
                else:
                    app.logger.error(f"Invalid file type: {file.filename}")
                    return jsonify({"error": "Invalid file type"}), 400

            # Process files synchronously
            try:
                app.logger.info("Processing files synchronously...")
                results = process_audio_files(filenames)
                app.logger.info("Processing complete")
                return jsonify(results), 200
            except Exception as e:
                app.logger.error(f"Error processing files: {str(e)}")
                app.logger.error(traceback.format_exc())
                cleanup_files(filenames)
                return jsonify({"error": f"Error processing files: {str(e)}"}), 500
        except Exception as e:
            app.logger.error(f"Unexpected error in index route: {str(e)}")
            app.logger.error(traceback.format_exc())
            return jsonify({"error": "An unexpected error occurred. Please try again."}), 500

    return render_template('index.html')

def process_audio_files(filenames):
    app.logger.info(f"Starting to process {len(filenames)} files")
    results = []
    
    try:
        for filepath in filenames:
            app.logger.info(f"Processing file: {filepath}")
            try:
                app.logger.info(f"Analyzing audio file: {filepath}")
                analysis_results, waveform_img, spectrogram_img = analyze_audio(filepath)
                app.logger.info(f"Analysis complete for: {filepath}")
                results.append({
                    "filename": os.path.basename(filepath),
                    "analysis": analysis_results,
                    "waveform_img": waveform_img,
                    "spectrogram_img": spectrogram_img
                })
            except Exception as e:
                app.logger.error(f"Error processing file {filepath}: {e}")
                app.logger.error(traceback.format_exc())
                results.append({
                    "filename": os.path.basename(filepath),
                    "error": str(e)
                })

        # Only generate comparisons for files that were successfully analyzed
        app.logger.info("Generating comparison graphs")
        valid_results = [r for r in results if "error" not in r]
        comparison_imgs = generate_comparison_graphs(valid_results) if len(valid_results) > 1 else None
        
        app.logger.info("Exporting PDF")
        pdf_buffer = export_pdf(results, comparison_imgs)
        
        app.logger.info("Exporting CSV")
        csv_buffer = export_csv(results)
        
        app.logger.info("Processing completed successfully")
        return {
            "results": results,
            "comparison_imgs": comparison_imgs,
            "pdf": base64.b64encode(pdf_buffer.getvalue()).decode('utf-8'),
            "csv": base64.b64encode(csv_buffer.getvalue()).decode('utf-8')
        }
    finally:
        # Always clean up files regardless of success or failure
        app.logger.info("Cleaning up files")
        cleanup_files(filenames)

def analyze_audio(file_path):
    app.logger.info(f"Starting analysis of: {file_path}")
    try:
        app.logger.info("Loading audio file with librosa")
        audio_data, rate = librosa.load(file_path, sr=None)
        app.logger.info(f"Audio loaded. Sample rate: {rate}, Shape: {audio_data.shape}")
        
        if audio_data.ndim > 1:
            app.logger.info("Converting stereo to mono")
            audio_data = audio_data.mean(axis=1)

        app.logger.info("Calculating true peak")
        true_peak = np.max(np.abs(audio_data))
        true_peak_dbfs = 20 * np.log10(true_peak)
        app.logger.info(f"True peak: {true_peak_dbfs} dBFS")

        app.logger.info("Calculating RMS")
        rms_value = np.sqrt(np.mean(np.square(audio_data)))
        rms_db = 20 * np.log10(rms_value)
        app.logger.info(f"RMS: {rms_db} dB")

        app.logger.info("Calculating integrated loudness")
        meter = pyln.Meter(rate)
        loudness_integrated = meter.integrated_loudness(audio_data)
        app.logger.info(f"Integrated loudness: {loudness_integrated} LUFS")

        app.logger.info("Calculating momentary loudness")
        block_size_momentary = int(0.4 * rate)
        momentary_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_momentary])
                              for i in range(0, len(audio_data), block_size_momentary)
                              if len(audio_data[i:i + block_size_momentary]) == block_size_momentary]
        max_momentary_loudness = np.max(momentary_loudness) if momentary_loudness else float('nan')
        app.logger.info(f"Max momentary loudness: {max_momentary_loudness} LUFS")

        app.logger.info("Calculating short-term loudness")
        block_size_short_term = int(3 * rate)
        short_term_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_short_term])
                               for i in range(0, len(audio_data), block_size_short_term)
                               if len(audio_data[i:i + block_size_short_term]) == block_size_short_term]
        max_short_term_loudness = np.max(short_term_loudness) if short_term_loudness else float('nan')
        app.logger.info(f"Max short-term loudness: {max_short_term_loudness} LUFS")

        app.logger.info("Generating waveform")
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
        app.logger.info("Waveform generated")

        app.logger.info("Generating spectrogram")
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
        app.logger.info("Spectrogram generated")

        app.logger.info("Audio analysis complete")
        return {
                "true_peak_dbfs": true_peak_dbfs,
                "rms_db": rms_db,
                "loudness_integrated": loudness_integrated,
                "max_momentary_loudness": max_momentary_loudness,
                "max_short_term_loudness": max_short_term_loudness
            }, waveform_img, spectrogram_img
    except Exception as e:
        app.logger.error(f"Error analyzing audio: {str(e)}")
        app.logger.error(traceback.format_exc())
        raise

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
        if "error" in result:
            p.drawString(30, y, f'File: {result["filename"]} (Error: {result["error"]})')
            y -= 40
            continue

        p.drawString(30, y, f'File: {result["filename"]}')
        y -= 20
        
        if "analysis" in result:
            for metric, value in result["analysis"].items():
                p.drawString(30, y, f'{metric.replace("_", " ").capitalize()}: {value:.2f}')
                y -= 20

            # Wrap the BytesIO with ImageReader
            img_data = base64.b64decode(result["waveform_img"])
            p.drawImage(ImageReader(io.BytesIO(img_data)), 30, y - 200, width=500, height=200)
            y -= 220
            
            img_data = base64.b64decode(result["spectrogram_img"])
            p.drawImage(ImageReader(io.BytesIO(img_data)), 30, y - 200, width=500, height=200)
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
            p.drawImage(ImageReader(io.BytesIO(base64.b64decode(img_data))), 30, y - 300, width=500, height=300)
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
            app.logger.info(f"Deleting file: {filename}")
            if os.path.exists(filename):
                os.remove(filename)
                app.logger.info(f"File deleted: {filename}")
            else:
                app.logger.warning(f"File not found for deletion: {filename}")
        except Exception as e:
            app.logger.error(f"Error deleting file {filename}: {e}")
            app.logger.error(traceback.format_exc())

@app.errorhandler(413)
def file_too_large(error):
    return jsonify({"error": "File too large. Max file size exceeded."}), 413

# Add general error handler
@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {str(e)}")
    return jsonify({"error": "Server error. Please try again later."}), 500

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.logger.info("Starting Flask server")
    app.run(debug=True)
