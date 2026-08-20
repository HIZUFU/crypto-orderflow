"""Apply trained CatBoost model to filter signals in production."""
from pathlib import Path

import numpy as np
from catboost import CatBoostClassifier


class SignalFilter:
    """CatBoost-based meta-labeling filter for order-flow signals."""

    def __init__(self, model_path: Path = Path("data/models/signal_filter.cbm")) -> None:
        self.model_path = model_path
        self.model: CatBoostClassifier | None = None
        self.feature_columns = [
            "mid_price", "spread_bps", "imbalance", "microprice", "microprice_offset_bps",
            "buy_volume_3s", "sell_volume_3s", "delta_ratio_3s", "trades_3s", "trade_intensity",
            "volatility_30s", "book_depth_bid", "book_depth_ask",
        ]
        if model_path.exists():
            self.load()

    def load(self) -> None:
        """Load trained model from disk."""
        self.model = CatBoostClassifier()
        self.model.load_model(str(self.model_path))

    def predict_proba(self, features: dict[str, float], rule_score: float) -> float:
        """Return calibrated probability of signal success. Falls back to rule score if model unavailable."""
        if self.model is None:
            return rule_score
        feature_vector = [features.get(col, 0.0) for col in self.feature_columns]
        feature_vector.append(rule_score)
        proba = self.model.predict_proba(np.array([feature_vector]))[0, 1]
        return float(proba)

    def should_alert(self, features: dict[str, float], rule_score: float, threshold: float = 0.55) -> bool:
        """Return True if signal passes model threshold."""
        return self.predict_proba(features, rule_score) >= threshold
