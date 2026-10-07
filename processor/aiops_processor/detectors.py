"""Lightweight detectors: EWMA control chart (time-series baseline), Isolation Forest (multivariate), linear-trend forecaster."""
import math

import numpy as np
from sklearn.ensemble import IsolationForest


class Ewma:
    """EWMA mean/variance baseline. z-score is computed against the baseline; the baseline is frozen while anomalous."""

    def __init__(self, alpha=0.03, warm=25, floor=1.0):
        self.alpha, self.warm, self.floor = alpha, warm, floor
        self.n, self.mean, self.var = 0, 0.0, 0.0

    @property
    def ready(self):
        return self.n >= self.warm

    def z(self, x):
        if not self.ready:
            return 0.0
        return (x - self.mean) / max(math.sqrt(self.var), self.floor)

    def update(self, x):
        self.n += 1
        a = max(self.alpha, 1.0 / self.n)           # cumulative mean while warming up
        d = x - self.mean
        self.mean += a * d
        self.var = (1 - a) * (self.var + a * d * d)


class MultiVariate:
    """Per-service Isolation Forest trained on recent *normal* feature vectors."""

    def __init__(self, min_train=60, retrain_every=240, max_rows=600):
        self.rows, self.model, self.min_train, self.retrain_every, self.max_rows = [], None, min_train, retrain_every, max_rows
        self.since_fit = 0

    def observe_normal(self, x):
        self.rows.append(x)
        self.rows = self.rows[-self.max_rows:]
        self.since_fit += 1
        if len(self.rows) >= self.min_train and (self.model is None or self.since_fit >= self.retrain_every):
            self.model = IsolationForest(n_estimators=100, contamination=0.01, random_state=0).fit(np.array(self.rows))
            self.since_fit = 0

    def score(self, x):
        """decision_function: negative = outlier. None while still training."""
        return None if self.model is None else float(self.model.decision_function([x])[0])


def forecast(points, key, limit, min_slope, window=30, min_r2=0.8):
    """Fit a line to the last `window` samples; return ETA (seconds) to `limit` if the trend is steep and clean."""
    pts = points[-window:]
    if len(pts) < 12:
        return None
    t = np.array([p["ts"] for p in pts]) - pts[0]["ts"]
    y = np.array([p[key] for p in pts], dtype=float)
    if t[-1] <= 0:
        return None
    slope, icpt = np.polyfit(t, y, 1)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(((y - (slope * t + icpt)) ** 2).sum()) / ss_tot if ss_tot > 1e-9 else 0.0
    if slope < min_slope or r2 < min_r2 or y[-1] >= limit:
        return None
    return {"eta_s": round(float((limit - y[-1]) / slope), 1), "slope": round(float(slope), 3),
            "current": round(float(y[-1]), 1), "confidence": round(float(r2), 2)}
