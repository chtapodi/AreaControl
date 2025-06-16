import numpy as np

class ColorCalibrator:
    """Compute and apply color calibration for arbitrary channel counts."""

    def __init__(self, sample_pairs, input_dim=None):
        """Create a calibration from sample pairs.

        ``sample_pairs`` should be an iterable of ``(desired, actual)`` tuples
        where ``desired`` is the requested color (typically RGB) and ``actual``
        is the raw command needed for the specific light. ``actual`` may contain
        any number of channels (e.g. RGBW, RGBWW).

        ``input_dim`` can be used to explicitly specify the length of the
        ``desired`` color. If omitted it will be inferred from the first sample.
        """

        self.input_dim = input_dim if input_dim is not None else len(sample_pairs[0][0])
        self.matrix = self._compute_matrix(sample_pairs)

    def _compute_matrix(self, pairs):
        """Solve the least-squares transformation matrix."""
        M = []
        Y = []
        for desired, raw in pairs:
            if len(desired) != self.input_dim:
                raise ValueError("All desired colors must have the same length")
            M.append(list(desired) + [1])
            Y.append(list(raw))
        M = np.asarray(M, dtype=float)
        Y = np.asarray(Y, dtype=float)
        A, _, _, _ = np.linalg.lstsq(M, Y, rcond=None)
        return A

    def apply(self, color):
        vec = np.asarray(list(color) + [1], dtype=float)
        corrected = np.dot(vec, self.matrix)
        corrected = np.clip(corrected, 0, 255)
        return [int(round(x)) for x in corrected]


class LightCalibrationMixin:
    """Mixin adding color calibration support to light drivers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calibrator = None

    def set_calibrator(self, calibrator):
        self.calibrator = calibrator

    def calibrate(self, sample_pairs, input_dim=None):
        self.calibrator = ColorCalibrator(sample_pairs, input_dim=input_dim)

    def apply_calibration(self, color):
        if self.calibrator is not None and color is not None:
            return self.calibrator.apply(color)
        return color

