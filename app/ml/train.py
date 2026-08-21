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
    
    # Merge alerts with trades
    merged = alerts.merge(trades[["alert_id", "pnl", "exit_reason"]], on="alert_id", how="left")
    
    # CRITICAL FIX: Filter out rows with NaN pnl BEFORE creating labels
    # This ensures we only train on alerts that have completed trades
    merged = merged[merged["pnl"].notna()].copy()
    
    # Now create binary labels: 1 if profitable, 0 otherwise
    merged["label"] = (merged["pnl"] > 0).astype(int)
    
    print(f"Total alerts: {len(alerts)}")
    print(f"Matched with closed trades: {len(merged)}")
    print(f"Profitable trades: {merged['label'].sum()} ({merged['label'].mean():.1%})")
    
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
        raise ValueError(f"Not enough closed trades for training: {len(y)} samples (need at least 50)")
    
    train_pool = Pool(X, y, cat_features=categorical_features)
    model = CatBoostClassifier(
        iterations=500,
        depth=4,
        learning_rate=0.05,
        loss_function="Logloss",
        verbose=50,
        random_seed=42,
        eval_metric="AUC",
    )
    model.fit(train_pool)
    
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_path))
    print(f"\n✓ Model saved to {model_path}")
    
    print("\nFeature importances:")
    importances = sorted(zip(feature_columns, model.feature_importances_), key=lambda x: x[1], reverse=True)
    for name, importance in importances:
        print(f"  {name:.<30} {importance:.3f}")


if __name__ == "__main__":
    data = load_training_data()
    print(f"\n{'='*60}")
    print(f"Training CatBoost meta-labeling filter")
    print(f"{'='*60}\n")
    train_catboost(data)
    print(f"\n{'='*60}")
    print("Training complete! Set USE_ML_FILTER=true in .env to enable.")
    print(f"{'='*60}\n")
