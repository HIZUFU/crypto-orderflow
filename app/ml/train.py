"""Train a CatBoost meta-label model from all measured alert outcomes."""
from pathlib import Path

import pandas as pd
from catboost import CatBoostClassifier, Pool
from sklearn.metrics import accuracy_score, roc_auc_score

from app.ml.filter import FEATURE_COLUMNS


def load_training_data(history_dir: Path = Path("data/history")) -> pd.DataFrame:
    path = history_dir / "training.parquet"
    if not path.exists():
        raise ValueError(f"No training dataset found in {history_dir}; run python -m app.ml.export first")
    dataset = pd.read_parquet(path)
    if dataset.empty:
        raise ValueError("Training dataset is empty")
    return dataset


def train_catboost(
    dataset: pd.DataFrame, model_path: Path = Path("data/models/signal_filter.cbm")
) -> dict:
    if "score" in dataset.columns and "rule_score" not in dataset.columns:
        dataset = dataset.rename(columns={"score": "rule_score"})
    missing = [column for column in FEATURE_COLUMNS if column not in dataset.columns]
    if missing:
        raise ValueError(f"Missing training features: {', '.join(missing)}")
    if len(dataset) < 50:
        raise ValueError(f"Not enough labeled alerts: {len(dataset)} samples; need at least 50")
    if dataset["label"].nunique() < 2:
        raise ValueError("Training data must contain both winning and losing labels")

    dataset = dataset.sort_values("created_at").copy()
    split = max(int(len(dataset) * 0.8), 1)
    train = dataset.iloc[:split]
    test = dataset.iloc[split:]
    if test.empty or train["label"].nunique() < 2 or test["label"].nunique() < 2:
        raise ValueError("Time split must contain both labels in train and test portions")

    X_train = train[FEATURE_COLUMNS].fillna(0.0)
    y_train = train["label"]
    X_test = test[FEATURE_COLUMNS].fillna(0.0)
    y_test = test["label"]
    model = CatBoostClassifier(
        iterations=400,
        depth=4,
        learning_rate=0.05,
        loss_function="Logloss",
        verbose=False,
        random_seed=42,
    )
    model.fit(Pool(X_train, y_train))
    probabilities = model.predict_proba(X_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    metrics = {
        "samples": int(len(dataset)),
        "train_samples": int(len(train)),
        "test_samples": int(len(test)),
        "paper_trade_labels": int((dataset.get("label_source") == "paper_trade").sum()),
        "expired_mark_labels": int((dataset.get("label_source") == "expired_mark").sum()),
        "test_accuracy": float(accuracy_score(y_test, predictions)),
        "test_auc": float(roc_auc_score(y_test, probabilities)),
        "label_rate": float(dataset["label"].mean()),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(model_path))
    return metrics


if __name__ == "__main__":
    print(train_catboost(load_training_data()))
