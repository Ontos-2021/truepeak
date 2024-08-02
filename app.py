import os
from flask import Flask, request, render_template, redirect, url_for
from werkzeug.utils import secure_filename
import scipy.io.wavfile as wavfile
import numpy as np
from pydub import AudioSegment

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'tmp'  # Configura aquí la carpeta de uploads

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files['file']
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            if not os.path.exists(app.config['UPLOAD_FOLDER']):
                os.makedirs(app.config['UPLOAD_FOLDER'])  # Crea la carpeta si no existe
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            if filename.endswith('.mp3'):
                audio_path = convert_to_wav(filepath)
            else:
                audio_path = filepath
            true_peak_dbfs = analyze_true_peak(audio_path)
            os.remove(filepath)  # Limpieza del archivo almacenado
            if filename.endswith('.mp3'):
                os.remove(audio_path)  # Limpieza del archivo WAV convertido
            return render_template('index.html', result=f"The true peak of the audio file is: {true_peak_dbfs} dBFS")
    return render_template('index.html', result=None)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'wav', 'mp3'}

def convert_to_wav(mp3_path):
    wav_path = mp3_path.rsplit('.', 1)[0] + '.wav'
    audio = AudioSegment.from_file(mp3_path)
    audio.export(wav_path, format='wav')
    return wav_path

def analyze_true_peak(wav_path):
    rate, audio_data = wavfile.read(wav_path)
    if audio_data.dtype == np.int16:
        audio_data = audio_data.astype(np.float32) / np.iinfo(np.int16).max
    elif audio_data.dtype == np.int32:
        audio_data = audio_data.astype(np.float32) / np.iinfo(np.int32).max
    true_peak = np.max(np.abs(audio_data))
    true_peak_dbfs = 20 * np.log10(true_peak)
    return true_peak_dbfs

if __name__ == '__main__':
    app.run(debug=True)
