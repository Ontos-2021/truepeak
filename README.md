# Audio Analysis Tool

## Descripción del Proyecto
El proyecto **Audio Analysis Tool** es una aplicación web desarrollada con Flask, diseñada para proporcionar herramientas de análisis de audio necesarias para la masterización de música. Este programa permite a los usuarios cargar archivos de audio (en formatos WAV y MP3) y obtener varias métricas importantes como el True Peak, RMS, Loudness Integrado, y los valores máximos de Loudness Momentáneo y a Corto Plazo.

## Características
- Análisis de True Peak en dBFS.
- Cálculo de RMS en dB.
- Medición de Loudness Integrado en LUFS.
- Determinación de los valores máximos de Loudness Momentáneo y a Corto Plazo en LUFS.
- Soporte para múltiples archivos de audio simultáneamente.
- Visualización de forma de onda y espectrograma por archivo.
- Gráficos de comparación de métricas entre tracks.
- Exportación de reporte en PDF (descarga automática al finalizar el análisis) y de datos en CSV.

## Requisitos del Sistema
- Python 3.7 o superior
- pip (el gestor de paquetes de Python)

## Instalación y Configuración

### Windows

1. **Descargar y descomprimir el proyecto**:
   - Descarga el repositorio del proyecto desde GitHub.
   - Descomprime el archivo en una ubicación de tu elección.

2. **Crear y activar un entorno virtual**:
   - Abre una terminal de comandos (cmd) y navega al directorio del proyecto.
   - Ejecuta los siguientes comandos:
     ```sh
     python -m venv env
     env\Scripts\activate
     ```

3. **Instalar las dependencias**:
   - Con el entorno virtual activado, instala las dependencias necesarias:
     ```sh
     pip install -r requirements.txt
     ```

4. **Ejecutar la aplicación**:
   - Una vez instaladas las dependencias, inicia la aplicación Flask:
     ```sh
     python app.py
     ```

5. **Abrir la aplicación en el navegador**:
   - Abre tu navegador y navega a `http://127.0.0.1:5000` para utilizar la herramienta de análisis de audio.

### Mac

1. **Descargar y descomprimir el proyecto**:
   - Descarga el repositorio del proyecto desde GitHub.
   - Descomprime el archivo en una ubicación de tu elección.

2. **Crear y activar un entorno virtual**:
   - Abre una terminal y navega al directorio del proyecto.
   - Ejecuta los siguientes comandos:
     ```sh
     python3 -m venv env
     source env/bin/activate
     ```

3. **Instalar las dependencias**:
   - Con el entorno virtual activado, instala las dependencias necesarias:
     ```sh
     pip install -r requirements.txt
     ```

4. **Ejecutar la aplicación**:
   - Una vez instaladas las dependencias, inicia la aplicación Flask:
     ```sh
     python app.py
     ```

5. **Abrir la aplicación en el navegador**:
   - Abre tu navegador y navega a `http://127.0.0.1:5000` para utilizar la herramienta de análisis de audio.

## Uso de la Aplicación
1. **Subir archivos de audio**:
   - Utiliza el formulario en la página principal para cargar uno o varios archivos de audio en formato WAV o MP3.

2. **Ver los resultados**:
   - La aplicación procesará los archivos y mostrará los resultados de análisis para cada archivo, incluyendo True Peak, RMS, Loudness Integrado, y los valores máximos de Loudness Momentáneo y a Corto Plazo, junto con la forma de onda, el espectrograma y los gráficos de comparación.

3. **Descargar los resultados**:
   - El reporte PDF se descarga automáticamente al terminar el análisis. Los botones *Download PDF Report* y *Download CSV Data* permiten volver a descargarlos en cualquier momento.

4. **Casos especiales**:
   - Archivos demasiado cortos para medir loudness muestran `N/A` en esas métricas pero se analizan igual.
   - Archivos corruptos o ilegibles no detienen el análisis del resto: se listan con su error y se omiten del CSV y del reporte PDF.

## Endpoints de la API
| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/` | Página principal. |
| `POST` | `/analyze` | Sube uno o varios archivos (multipart, campo `file`) y devuelve métricas e imágenes en JSON. |
| `POST` | `/export/pdf` | Recibe el JSON de `/analyze` (campos `results` y `comparison_imgs`) y devuelve el reporte PDF. |
| `POST` | `/export/csv` | Recibe el JSON de `/analyze` (campo `results`) y devuelve los datos en CSV. |

El límite de subida es de 200 MB por request y cada IP está limitada a 10 análisis por minuto.

## Ejecutar los Tests
Se incluye una suite de pruebas con audio sintético (no requiere archivos reales):

```sh
pip install -r requirements-dev.txt
python -m pytest tests
```

## Pantallazo de la Aplicación
![Pantallazo de la Aplicación](Truepeak.png)

## Contribuciones
Las contribuciones son bienvenidas. Si deseas contribuir al proyecto, por favor sigue estos pasos:
1. Haz un fork del repositorio.
2. Crea una rama con una nueva característica (`git checkout -b feature/nueva-caracteristica`).
3. Realiza los commits necesarios (`git commit -am 'Añadir nueva característica'`).
4. Haz push a la rama (`git push origin feature/nueva-caracteristica`).
5. Abre un Pull Request.

## Licencia
Este proyecto está licenciado bajo la Licencia MIT. Consulta el archivo `LICENSE` para obtener más detalles.

---

Desarrollado por [José Mercado].

## Contacto
Sígueme en Instagram: [josemercado.music](https://www.instagram.com/josemercado.music)
