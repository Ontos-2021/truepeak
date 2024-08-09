from flask import Flask, request, render_template, send_file
from werkzeug.utils import secure_filename
import librosa
import numpy as np
import pyloudnorm as pyln
import pandas as pd
import matplotlib

matplotlib.use('Agg')  # Usar backend 'Agg' para evitar problemas con hilos
import matplotlib.pyplot as plt
import librosa.display
import os
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = Flask(__name__)

STATIC_FOLDER = 'static/generated_images'
TEMP_FOLDER = 'temp'


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        files = request.files.getlist('file')
        results = []
        pdf_path = None
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(TEMP_FOLDER, filename)
                file.save(filepath)
                analysis_results, waveform_img_web, spectrogram_img_web, waveform_img_pdf, spectrogram_img_pdf = analyze_audio(
                    filepath)
                results.append({
                    "filename": filename,
                    "analysis": analysis_results,
                    "waveform_img": waveform_img_web,
                    "spectrogram_img": spectrogram_img_web,
                    "waveform_img_pdf": waveform_img_pdf,
                    "spectrogram_img_pdf": spectrogram_img_pdf,
                })

        comparison_imgs = None
        if len(results) > 1:
            comparison_imgs = generate_comparison_graphs(results)

        if 'download' in request.form:
            return download_results(results)
        elif 'export_pdf' in request.form:
            pdf_buffer = export_pdf(results, comparison_imgs)
            pdf_path = os.path.join(STATIC_FOLDER, 'audio_analysis.pdf')
            with open(pdf_path, 'wb') as f:
                f.write(pdf_buffer.getvalue())

            # Descargar el PDF inmediatamente después de generarlo
            return send_file(pdf_path, as_attachment=True, download_name='audio_analysis.pdf', mimetype='application/pdf')

        return render_template('index.html', results=results, comparison_imgs=comparison_imgs)
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

    # Guardar la forma de onda para la web en la carpeta static
    waveform_path_web = os.path.join(STATIC_FOLDER, f'{os.path.basename(file_path)}_waveform_web.png')
    fig, ax = plt.subplots()
    librosa.display.waveshow(audio_data, sr=rate, ax=ax)
    ax.set_title('Waveform')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Amplitude')
    plt.savefig(waveform_path_web)
    plt.close(fig)

    # Guardar la forma de onda para el PDF en la carpeta static
    waveform_path_pdf = os.path.join(STATIC_FOLDER, f'{os.path.basename(file_path)}_waveform_pdf.png')
    fig, ax = plt.subplots()
    librosa.display.waveshow(audio_data, sr=rate, ax=ax)
    ax.set_title('Waveform')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Amplitude')
    plt.savefig(waveform_path_pdf)
    plt.close(fig)

    # Guardar el espectrograma para la web en la carpeta static
    spectrogram_path_web = os.path.join(STATIC_FOLDER, f'{os.path.basename(file_path)}_spectrogram_web.png')
    fig, ax = plt.subplots()
    S = librosa.feature.melspectrogram(y=audio_data, sr=rate)
    S_dB = librosa.power_to_db(S, ref=np.max)
    img = librosa.display.specshow(S_dB, sr=rate, x_axis='time', y_axis='mel', ax=ax)
    fig.colorbar(img, ax=ax, format='%+2.0f dB')
    ax.set_title('Mel-frequency spectrogram')
    plt.savefig(spectrogram_path_web)
    plt.close(fig)

    # Guardar el espectrograma para el PDF en la carpeta static
    spectrogram_path_pdf = os.path.join(STATIC_FOLDER, f'{os.path.basename(file_path)}_spectrogram_pdf.png')
    fig, ax = plt.subplots()
    S = librosa.feature.melspectrogram(y=audio_data, sr=rate)
    S_dB = librosa.power_to_db(S, ref=np.max)
    img = librosa.display.specshow(S_dB, sr=rate, x_axis='time', y_axis='mel', ax=ax)
    fig.colorbar(img, ax=ax, format='%+2.0f dB')
    ax.set_title('Mel-frequency spectrogram')
    plt.savefig(spectrogram_path_pdf)
    plt.close(fig)

    return {
               "true_peak_dbfs": true_peak_dbfs,
               "rms_db": rms_db,
               "loudness_integrated": loudness_integrated,
               "max_momentary_loudness": max_momentary_loudness,
               "max_short_term_loudness": max_short_term_loudness
           }, waveform_path_web, spectrogram_path_web, waveform_path_pdf, spectrogram_path_pdf


def generate_comparison_graphs(results):
    metrics = ["true_peak_dbfs", "rms_db", "loudness_integrated", "max_momentary_loudness", "max_short_term_loudness"]
    comparison_imgs = {}
    filenames = [result["filename"] for result in results]

    for metric in metrics:
        values = [result["analysis"][metric] for result in results]
        fig, ax = plt.subplots()
        ax.bar(filenames, values)
        ax.set_title(f'Comparison of {metric.replace("_", " ").capitalize()}')
        ax.set_xlabel('Track')
        ax.set_ylabel(metric.replace('_', ' ').capitalize())

        # Guardar la figura en un archivo temporal dentro de static
        comparison_path = os.path.join(STATIC_FOLDER, f'comparison_{metric}.png')
        plt.savefig(comparison_path)
        plt.close(fig)

        # Guardar el path de la imagen
        comparison_imgs[metric] = comparison_path

    return comparison_imgs


def export_pdf(results, comparison_imgs):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica", 12)

    # Añadir análisis de pista por página
    for result in results:
        y = height - 40
        p.drawString(30, y, f'File: {result["filename"]}')
        y -= 20
        for metric, value in result["analysis"].items():
            p.drawString(30, y, f'{metric.replace("_", " ").capitalize()}: {value}')
            y -= 20

        # Añadir imágenes de forma de onda y espectrograma (versión PDF)
        waveform_path_pdf = result["waveform_img_pdf"]
        spectrogram_path_pdf = result["spectrogram_img_pdf"]
        p.drawImage(waveform_path_pdf, 30, y - 150, width=width - 60, height=100)
        y -= 170
        p.drawImage(spectrogram_path_pdf, 30, y - 150, width=width - 60, height=100)
        y -= 170

        p.showPage()  # Nueva página para cada pista

    # Añadir comparaciones, dos imágenes por página
    if comparison_imgs:
        y = height - 40
        count = 0
        for metric, img_path in comparison_imgs.items():
            p.drawString(30, y, f'Comparison of {metric.replace("_", " ").capitalize()}')
            y -= 20
            p.drawImage(img_path, 30, y - 200, width=width - 60, height=200)
            y -= 220
            count += 1
            if count % 2 == 0:
                p.showPage()
                y = height - 40

    p.save()
    buffer.seek(0)

    return buffer


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


def cleanup_files(results, comparison_imgs, extra_files=[]):
    for result in results:
        try:
            os.remove(result["waveform_img"])
            os.remove(result["spectrogram_img"])
            os.remove(result["waveform_img_pdf"])
            os.remove(result["spectrogram_img_pdf"])
        except Exception as e:
            print(f"Error deleting file: {e}")

    if comparison_imgs:
        for img in comparison_imgs.values():
            try:
                os.remove(img)
            except Exception as e:
                print(f"Error deleting file: {e}")

    for file in extra_files:
        try:
            os.remove(file)
        except Exception as e:
            print(f"Error deleting file: {e}")


if __name__ == '__main__':
    if not os.path.exists(STATIC_FOLDER):
        os.makedirs(STATIC_FOLDER)
    if not os.path.exists(TEMP_FOLDER):
        os.makedirs(TEMP_FOLDER)
    app.run(debug=True)
