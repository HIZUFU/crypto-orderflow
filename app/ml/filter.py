"""Apply a trained CatBoost model to filter candidate signals."""
from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    from catboost import CatBoostClassifier
except ImportError:  # ML is optional when the application runs in rule-only mode.
    CatBoostClassifier = None  # type: ignore[assignment,misc]


FEATURE_COLUMNS = [
    "mid_price", "spread_bps", "imbalance", "microprice", "microprice_offset_bps",
    "buy_volume_3s", "sell_volume_3s", "delta_ratio_3s", "trades_3s", "trade_intensity",
    "volatility_30s", "book_depth_bid", "book_depth_ask", "rule_score",
]


class SignalFilter:
    def __init__(self, model_path: Path = Path("data/models/signal_filter.cbm")) -> None:
        self.model_path = Path(model_path)
        self.model: CatBoostClassifier | None = None
        if self.model_path.exists():
            self.load()

    def load(self) -> None:
        if CatBoostClassifier is None:
            raise RuntimeError("CatBoost is not installed; install the ML dependencies to load a model")
        self.model = CatBoostClassifier()
        self.model.load_model(str(self.model_path))

    def predict_proba(self, features: dict[str, float], rule_score: float) -> float:
        if self.model is None:
            return rule_score
        vector = [features.get(name, 0.0) if name != "rule_score" else rule_score for name in FEATURE_COLUMNS]
        return float(self.model.predict_proba(np.asarray([vector], dtype=float))[0, 1])

    def should_alert(self, features: dict[str, float], rule_score: float, threshold: float = 0.55) -> bool:
        return self.predict_proba(features, rule_score) >= threshold
