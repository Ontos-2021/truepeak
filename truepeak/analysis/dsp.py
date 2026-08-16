import numpy as np
import soundfile as sf

ALLOWED_EXTENSIONS = {"wav", "wave", "mp3", "flac", "ogg", "aiff", "aif"}

DEFAULT_CHANNEL_WEIGHTS = {
    1: (1.0,),
    2: (1.0, 1.0),
    3: (1.0, 1.0, 1.0),
    4: (1.0, 1.0, 1.0, 0.0),
    5: (1.0, 1.0, 1.0, 1.41, 1.41),
    6: (1.0, 1.0, 1.0, 0.0, 1.41, 1.41),
    7: (1.0, 1.0, 1.0, 1.41, 1.41, 1.0, 1.0),
    8: (1.0, 1.0, 1.0, 0.0, 1.41, 1.41, 1.0, 1.0),
}


def channel_weights(n_channels):
    return DEFAULT_CHANNEL_WEIGHTS.get(n_channels, (1.0,) * n_channels)


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


class ArrayProvider:
    def __init__(self, audio, sr):
        audio = np.asarray(audio)
        if audio.ndim == 1:
            audio = audio[:, None]
        self.audio = np.asarray(audio, dtype=np.float64)
        self.sr = int(sr)

    def info(self):
        frames, nch = self.audio.shape
        return self.sr, nch, frames

    def blocks(self, size):
        for start in range(0, self.audio.shape[0], size):
            yield self.audio[start:start + size]


class FileProvider:
    def __init__(self, path):
        self.path = path
        self._info = None

    def info(self):
        if self._info is None:
            self._info = sf.info(self.path)
        return self._info.samplerate, self._info.channels, self._info.frames

    def blocks(self, size):
        return sf.blocks(
            self.path,
            blocksize=size,
            dtype="float64",
            always_2d=True,
        )


def load_audio(path, dtype="float32"):
    audio, sr = sf.read(path, dtype=dtype, always_2d=True)
    return np.asarray(audio), int(sr)
