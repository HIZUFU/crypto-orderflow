"""Train CatBoost classifier for meta-labeling: filter weak signals."""
from pathlib import Path

import pandas as pd
from catboost import CatBoostClassifier, Pool


def load_training_data(history_dir: Path = Path("data/history")) -> pd.DataFrame:
    """Load alerts and trades from Parquet, join them for labeling."""
    alerts_files = sorted(history_dir.glob("alerts_*.parquet"))
    trades_files = sorted(history_dir.glob("trades_*.parquet"))
    if not alerts_files or not trades_files:
        raise ValueError(f"No training data found in {history_dir}")
    alerts = pd.concat([pd.read_parquet(f) for f in alerts_files], ignore_index=True)
    trades = pd.concat([pd.read_parquet(f) for f in trades_files], ignore_index=True)
    trades = trades[trades["status"] == "closed"]
    merged = alerts.merge(trades[["alert_id", "pnl", "exit_reason"]], on="alert_id", how="left")
    merged["label"] = (merged["pnl"] > 0).astype(int)
    merged = merged.dropna(subset=["label"])
    return merged


def train_catboost(dataset: pd.DataFrame, model_path: Path = Path("data/models/signal_filter.cbm")) -> None:
    """Train CatBoost meta-labeling classifier."""
    feature_columns = [
        "mid_price", "spread_bps", "imbalance", "microprice", "microprice_offset_bps",
        "buy_volume_3s", "sell_volume_3s", "delta_ratio_3s", "trades_3s", "trade_intensity",
        "volatility_30s", "book_depth_bid", "book_depth_ask", "score",
    ]
    categorical_features = []
    X = dataset[feature_columns]
    y = dataset["label"]
    if len(y) < 50:
        raise ValueError(f"Not enough closed trades for training: {len(y)} samples")
    train_pool = Pool(X, y, cat_features=categorical_features)
    model = CatBoostClassifier(
        iterations=500,
        depth=4,
        learning_rate=0.05,
        loss_function="Logloss",
        verbose=50,
        random_seed=42,
    )
    model.fit(train_pool)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_path))
    print(f"Model saved to {model_path}")
    print("Feature importances:")
    for name, importance in zip(feature_columns, model.feature_importances_):
        print(f"  {name}: {importance:.3f}")


if __name__ == "__main__":
    data = load_training_data()
    print(f"Loaded {len(data)} labeled signals")
    print(f"Win rate: {data['label'].mean():.2%}")
    train_catboost(data)
