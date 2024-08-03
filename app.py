from flask import Flask, request, render_template, redirect, url_for
from werkzeug.utils import secure_filename
import librosa
import numpy as np
import pyloudnorm as pyln
import os

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        files = request.files.getlist('file')  # Obtener la lista de archivos
        results = []
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join('tmp', filename)
                file.save(filepath)
                analysis_results = analyze_audio(filepath)
                os.remove(filepath)  # Cleanup the stored file
                results.append((filename, analysis_results))
        return render_template('index.html', results=results)
    return render_template('index.html', results=None)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'wav', 'mp3'}

def analyze_audio(file_path):
    # Cargar archivo de audio
    audio_data, rate = librosa.load(file_path, sr=None)  # Cargar con su sample rate original
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)

    # Calcular True Peak
    true_peak = np.max(np.abs(audio_data))
    true_peak_dbfs = 20 * np.log10(true_peak)

    # Calcular RMS
    rms_value = np.sqrt(np.mean(np.square(audio_data)))
    rms_db = 20 * np.log10(rms_value)

    # Crear un medidor de sonoridad
    meter = pyln.Meter(rate)

    # Calcular Loudness Integrado
    loudness_integrated = meter.integrated_loudness(audio_data)

    # Calcular Loudness Momentáneo y su valor máximo
    block_size_momentary = int(0.4 * rate)
    momentary_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_momentary])
                          for i in range(0, len(audio_data), block_size_momentary)
                          if len(audio_data[i:i + block_size_momentary]) == block_size_momentary]
    max_momentary_loudness = np.max(momentary_loudness) if momentary_loudness else float('nan')

    # Calcular Loudness a Corto Plazo y su valor máximo
    block_size_short_term = int(3 * rate)
    short_term_loudness = [meter.integrated_loudness(audio_data[i:i + block_size_short_term])
                           for i in range(0, len(audio_data), block_size_short_term)
                           if len(audio_data[i:i + block_size_short_term]) == block_size_short_term]
    max_short_term_loudness = np.max(short_term_loudness) if short_term_loudness else float('nan')

    return {
        "true_peak_dbfs": true_peak_dbfs,
        "rms_db": rms_db,
        "loudness_integrated": loudness_integrated,
        "max_momentary_loudness": max_momentary_loudness,
        "max_short_term_loudness": max_short_term_loudness
    }

if __name__ == '__main__':
    app.run(debug=True)
