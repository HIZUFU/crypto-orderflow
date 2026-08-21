"""Train a CatBoost meta-label model from completed alert outcomes."""
from pathlib import Path

import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import accuracy_score, roc_auc_score

from app.ml.filter import FEATURE_COLUMNS


def load_training_data(history_dir: Path = Path("data/history")) -> pd.DataFrame:
    alerts_files = sorted(history_dir.glob("alerts_*.parquet"))
    trades_files = sorted(history_dir.glob("trades_*.parquet"))
    if not alerts_files or not trades_files:
        raise ValueError(f"No training data found in {history_dir}")
    alerts = pd.concat([pd.read_parquet(path) for path in alerts_files], ignore_index=True)
    trades = pd.concat([pd.read_parquet(path) for path in trades_files], ignore_index=True)
    trades = trades[trades["status"] == "closed"]
    merged = alerts.merge(trades[["alert_id", "pnl", "exit_reason"]], on="alert_id", how="inner")
    merged = merged[merged["pnl"].notna()].copy()
    merged["label"] = (merged["pnl"] > 0).astype(int)
    return merged


def train_catboost(dataset: pd.DataFrame, model_path: Path = Path("data/models/signal_filter.cbm")) -> dict:
    feature_columns = FEATURE_COLUMNS
    missing = [column for column in feature_columns if column not in dataset.columns and column != "rule_score"]
    if missing:
        raise ValueError(f"Missing training features: {', '.join(missing)}")
    if "score" in dataset.columns:
        dataset = dataset.rename(columns={"score": "rule_score"})
    if len(dataset) < 50:
        raise ValueError(f"Not enough closed trades for training: {len(dataset)} samples; need at least 50")
    dataset = dataset.sort_values("created_at" if "created_at" in dataset else dataset.index.name or "label")
    split = max(int(len(dataset) * 0.8), 1)
    train = dataset.iloc[:split]
    test = dataset.iloc[split:]
    if test.empty or train["label"].nunique() < 2:
        raise ValueError("Need both labels in the time-ordered train/test split")
    X_train = train[feature_columns].fillna(0.0)
    y_train = train["label"]
    X_test = test[feature_columns].fillna(0.0)
    y_test = test["label"]
    model = CatBoostClassifier(iterations=400, depth=4, learning_rate=0.05, loss_function="Logloss", verbose=False, random_seed=42)
    model.fit(Pool(X_train, y_train))
    probabilities = model.predict_proba(X_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    metrics = {
        "samples": int(len(dataset)),
        "train_samples": int(len(train)),
        "test_samples": int(len(test)),
        "test_accuracy": float(accuracy_score(y_test, predictions)),
        "test_auc": float(roc_auc_score(y_test, probabilities)) if y_test.nunique() > 1 else None,
        "label_rate": float(dataset["label"].mean()),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_path))
    return metrics


if __name__ == "__main__":
    data = load_training_data()
    print(train_catboost(data))
