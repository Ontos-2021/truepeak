from flask import Flask, request, render_template, redirect, url_for
from werkzeug.utils import secure_filename
import librosa
import numpy as np
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
                true_peak_dbfs = analyze_true_peak(filepath)
                os.remove(filepath)  # Cleanup the stored file
                results.append((filename, true_peak_dbfs))
        return render_template('index.html', results=results)
    return render_template('index.html', results=None)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'wav', 'mp3'}

def analyze_true_peak(file_path):
    # Cargar archivo de audio
    audio_data, rate = librosa.load(file_path, sr=None)  # Cargar con su sample rate original
    if audio_data.ndim > 1:
        audio_data = audio_data.mean(axis=1)
    true_peak = np.max(np.abs(audio_data))
    true_peak_dbfs = 20 * np.log10(true_peak)
    return true_peak_dbfs

if __name__ == '__main__':
    app.run(debug=True)
