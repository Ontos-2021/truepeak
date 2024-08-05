from flask import Flask, request, render_template, redirect, url_for, send_file
from werkzeug.utils import secure_filename
import librosa
import numpy as np
import pyloudnorm as pyln
import pandas as pd
import matplotlib

matplotlib.use('Agg')  # Usar backend 'Agg' para evitar problemas con hilos
import matplotlib.pyplot as plt
import os
import io
import base64

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        files = request.files.getlist('file')
        results = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join('tmp', filename)
                file.save(filepath)
                analysis_results, visualization = analyze_audio(filepath)
                os.remove(filepath)  # Cleanup the stored file
                results.append({
                    "filename": filename,
                    "analysis": analysis_results,
                    "visualization": visualization
                })

        if 'download' in request.form:
            return download_results(results)

        return render_template('index.html', results=results)
    return render_template('index.html', results=None)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'wav', 'mp3'}


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

    # Generar la visualización de la forma de onda
    fig, ax = plt.subplots()
    librosa.display.waveshow(audio_data, sr=rate, ax=ax)
    ax.set_title('Waveform')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Amplitude')

    # Guardar la figura en un buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close(fig)

    # Codificar la imagen en base64
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')

    return {
               "true_peak_dbfs": true_peak_dbfs,
               "rms_db": rms_db,
               "loudness_integrated": loudness_integrated,
               "max_momentary_loudness": max_momentary_loudness,
               "max_short_term_loudness": max_short_term_loudness
           }, img_base64


def download_results(results):
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

    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)

    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True,
                     download_name='analysis_results.csv')


if __name__ == '__main__':
    app.run(debug=True)
