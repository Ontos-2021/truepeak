# TruePeak - Mastering QC

Herramienta web de **control de calidad de mastering** para ingenieros de audio:
medición calibrada BS.1770/EBU R128, análisis de dinámica y estéreo, veredictos
de preparación por plataforma de streaming, comparación contra un track de
referencia, reportes PDF/CSV y normalización a target.

## Características

### Medición calibrada (ITU-R BS.1770-4 / EBU R128)
- **True peak real (dBTP)** por canal con oversampling 4x (detecta picos
  inter-muestra, validado contra la reconstrucción completa del filtro).
- **Sample peak (dBFS)**, RMS por canal y general, DC offset por canal.
- **Loudness integrado (LUFS)** con gating absoluto (-70 LUFS) y relativo (-10 LU),
  incluyendo canales con ponderación BS.1770 (estéreo y multicanal).
- **Momentary (400 ms) y short-term (3 s)** con ventanas deslizantes sin gating,
  tal como define el estándar.
- **LRA** (EBU Tech 3342) y **PLR**, **crest factor**.
- **Correlación de fase** L/R (global y mínima en 1 s) y **balance L/R**.
- **Detección de clipping** (eventos, samples totales, duración máxima) y
  **espectro promedio en bandas de 1/3 de octava** (30 bandas, 25 Hz - 20 kHz).
- Señal de calibración: seno de 997 Hz a -20 dBFS → -20.04 LUFS (stereo),
  con tolerancia ±0.1 LU frente a pyloudnorm y los archivos de prueba ITU.

### QC orientado al flujo de mastering
- **Análisis en el navegador (opción por defecto)**: el motor DSP completo está
  portado a JavaScript (`static/dsp.js`) y corre 100% local con Web Audio
  (`decodeAudioData`). Los archivos **no se suben al servidor** — ideal para
  masters largos o confidenciales. Si el navegador no puede decodificar o
  analizar, cae automáticamente al modo subida.
- **Veredictos por plataforma**: Spotify, Apple Music, YouTube, Tidal,
  Amazon Music (-2 dBTP), Deezer, SoundCloud, EBU R128 y ATSC A/85, con la
  ganancia de reproducción estimada ("Spotify te bajará 3.4 dB") y estado de
  true peak (OK / excede). Se calculan en el cliente desde `/api/targets`.
- **Timeline de loudness** (momentary + short-term + integrado + línea de
  target) y **waveform** renderizados en el navegador.
- **Vista de álbum/lote**: spread de LUFS, TP máximo, LRA promedio y gráficos
  comparativos entre tracks.
- **Track de referencia**: analiza un tema de referencia (localmente si es
  posible) y superpone su espectro promedio y su timeline de loudness sobre el
  track en análisis.
- **Reporte PDF con branding del estudio** (logo + nombre del estudio vía
  variables de entorno) y **CSV** exportables.

### Procesamiento
- **Normalización a target LUFS** con techo de true peak: ganancia segura,
  limitador de true peak opcional (pedalboard) cuando el techo no alcanza,
  y export WAV 24-bit con métricas antes/después.

### Arquitectura y robustez
- Motor DSP streaming por bloques (memoria acotada en archivos largos),
  límite de duración configurable, sanitización NaN/inf, errores por archivo
  que no tumban el lote.
- Rate limiting por IP, límite de subida, limpieza de temporales y tokens
  con TTL para descargas.
- Servidor de producción **waitress**, configuración por variables de entorno.
- Suite de tests con señales sintéticas de calibración + CI (GitHub Actions).

## Requisitos
- Python 3.9+
- pip

## Instalación

### Windows
```sh
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
python run.py
```

### Mac / Linux
```sh
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
python run.py
```

Abre `http://127.0.0.1:5000`.

## Uso
1. Arrastra uno o varios masters (WAV, MP3, FLAC, OGG, AIFF). Varios archivos =
   lote de álbum con comparación entre tracks.
2. *Analyze*: por defecto el análisis corre **en tu navegador** (sin subir
   audio). Desmarca "Analyze in browser (no upload)" para usar el servidor.
   Se muestran métricas calibradas, veredictos por plataforma, timeline de
   loudness, waveform y espectro promedio.
3. Opcional: agrega un track de referencia para superponer espectro/timeline.
4. *Normalize to target*: elige LUFS objetivo y techo de true peak para
   exportar un WAV 24-bit ajustado (requiere subir el archivo).
5. *Download PDF Report* / *Download CSV Data* para el reporte de QC.

Casos especiales:
- Archivos demasiado cortos para loudness muestran `N/A` en esas métricas
  pero se analizan igual.
- Archivos corruptos o ilegibles no detienen el análisis del resto: se listan
  con su error y se omiten del CSV y del PDF.

## Endpoints

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/` | Interfaz web. |
| `GET` | `/health` | Health check. |
| `GET` | `/api/targets` | Tabla de targets de plataformas. |
| `POST` | `/analyze` | Sube archivos (multipart, campo `file`) y devuelve métricas, series y veredictos en JSON. |
| `POST` | `/export/pdf` | Recibe el JSON de `/analyze` (`results`, `album`) y devuelve el reporte PDF. |
| `POST` | `/export/csv` | Recibe el JSON de `/analyze` (`results`) y devuelve CSV. |
| `POST` | `/normalize` | Archivo + `target_lufs`, `max_tp_dbtp`, `use_limiter` → JSON con métricas antes/después y URL de descarga. |
| `GET` | `/normalize/download/<token>` | Descarga el WAV normalizado (token con TTL). |

## Configuración por entorno

| Variable | Default | Descripción |
| --- | --- | --- |
| `TRUEPEAK_HOST` | `127.0.0.1` | Host del servidor. |
| `TRUEPEAK_PORT` | `5000` | Puerto. |
| `TRUEPEAK_TEMP_DIR` | `./temp` | Directorio de archivos temporales. |
| `TRUEPEAK_MAX_UPLOAD_MB` | `2048` | Límite de subida por request. |
| `TRUEPEAK_MAX_DURATION_MINUTES` | `180` | Duración máxima por archivo analizado. |
| `TRUEPEAK_MAX_NORMALIZE_MINUTES` | `180` | Duración máxima al normalizar. |
| `TRUEPEAK_RATE_LIMIT` | `1` | Habilita el rate limiting (0 = off). |
| `TRUEPEAK_RATE_MAX_CALLS` | `10` | Máximo de llamadas por ventana. |
| `TRUEPEAK_RATE_PER_SECONDS` | `60` | Ventana del rate limit en segundos. |
| `TRUEPEAK_NORMALIZE_TTL_SECONDS` | `600` | TTL de descargas normalizadas. |
| `TRUEPEAK_BRAND_NAME` | *(vacío)* | Nombre del estudio para la interfaz y los reportes PDF (ej. `Mi Estudio`). |
| `TRUEPEAK_BRAND_LOGO` | *(vacío)* | Ruta a un PNG con el logo del estudio (aparece en el PDF). |

## Tests

```sh
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
```

La suite incluye tests de calibración (señales de amplitud/frecuencia
conocidas, picos inter-muestra, gating, LRA, correlación, clipping, DC),
tests de **paridad JS vs Python** (el motor del navegador produce los mismos
valores: loudness ±0.05 LU, true peak ±0.05 dB, espectro ±0.5 dB; requieren
`node` en el PATH) y tests de API (análisis, exportaciones, branding del PDF,
normalización, rate limit, limpieza).

## Estructura

```
truepeak/
  analysis/     # motor DSP: metering BS.1770, true peak 4x, dinámica, estéreo, targets, normalización
  api/          # blueprints Flask, rate limit, token store
  export/       # reporte PDF (reportlab) y CSV
  viz/          # matplotlib (solo para el PDF; el navegador renderiza con canvas)
  config.py     # configuración por variables de entorno
templates/      # frontend (sin dependencias externas)
static/         # CSS, app.js (UI) y dsp.js (motor DSP JS — análisis local sin subir audio)
tests/          # suite con audio sintético + paridad JS vs Python
```

## Hoja de ruta (fuera de alcance actual)
- Cuentas e historial de análisis (SaaS freemium).
- Despliegue público en la nube.

## Licencia
MIT.

---

Desarrollado por [José Mercado](https://www.instagram.com/josemercado.music).
