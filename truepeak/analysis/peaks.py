import numpy as np
from scipy.signal import resample_poly

OVERSAMPLE = 4
GUARD = 512


class TruePeakScanner:
    def __init__(self, n_channels, guard=GUARD, oversample=OVERSAMPLE):
        self.n_channels = n_channels
        self.guard = guard
        self.oversample = oversample
        self.max_linear = np.zeros(n_channels)
        self._left = np.zeros((guard, n_channels))
        self._pending = None

    def _measure(self, pending, left, right):
        buf = np.concatenate((left, pending, right), axis=0)
        up = resample_poly(buf, self.oversample, 1, axis=0)
        i0 = self.guard * self.oversample
        i1 = (self.guard + pending.shape[0]) * self.oversample
        segment = np.abs(up[i0:i1])
        if segment.size:
            self.max_linear = np.maximum(
                self.max_linear, segment.max(axis=0)
            )

    def process(self, block):
        block = np.asarray(block, dtype=np.float64)
        if block.ndim == 1:
            block = block[:, None]
        if self._pending is not None:
            right = block[: self.guard]
            if right.shape[0] < self.guard:
                right = np.concatenate(
                    (
                        right,
                        np.zeros(
                            (self.guard - right.shape[0], block.shape[1])
                        ),
                    ),
                    axis=0,
                )
            self._measure(self._pending, self._left, right)
        if len(block) >= self.guard:
            if self._pending is not None:
                self._left = self._pending[-self.guard:].copy()
            self._pending = block
        elif len(block):
            if self._pending is None:
                self._pending = block
            else:
                self._pending = np.concatenate((self._pending, block), axis=0)

    def finish(self):
        if self._pending is not None and len(self._pending):
            right = np.zeros((self.guard, self._pending.shape[1]))
            self._measure(self._pending, self._left, right)
        self._pending = None
        return self.max_linear


def true_peak_db(max_linear):
    with np.errstate(divide="ignore", invalid="ignore"):
        return 20.0 * np.log10(np.asarray(max_linear, dtype=np.float64))
