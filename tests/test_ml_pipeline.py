"""Tests for ML pipeline in app/ml/filter.py and app/ml/train.py."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.ml.filter import SignalFilter


class TestSignalFilter:
    """Tests for SignalFilter class."""

    def test_predict_proba_returns_rule_score_when_no_model(self) -> None:
        """When model is not loaded, predict_proba should return rule_score."""
        filter_obj = SignalFilter(model_path=Path("/nonexistent/model.cbm"))
        features = {"mid_price": 100.0, "imbalance": 0.3}
        rule_score = 0.75
        
        result = filter_obj.predict_proba(features, rule_score)
        assert result == rule_score

    def test_should_alert_returns_false_when_no_model_and_low_score(self) -> None:
        """should_alert should return False when rule_score < threshold and no model."""
        filter_obj = SignalFilter(model_path=Path("/nonexistent/model.cbm"))
        features = {"mid_price": 100.0, "imbalance": 0.3}
        
        # Score below default threshold (0.55)
        result = filter_obj.should_alert(features, rule_score=0.4)
        assert result is False
        
        # Score above default threshold
        result = filter_obj.should_alert(features, rule_score=0.6)
        assert result is True

    def test_should_alert_with_custom_threshold(self) -> None:
        """should_alert should respect custom threshold parameter."""
        filter_obj = SignalFilter(model_path=Path("/nonexistent/model.cbm"))
        features = {"mid_price": 100.0, "imbalance": 0.3}
        
        # Score 0.5 with threshold 0.6 should be False
        result = filter_obj.should_alert(features, rule_score=0.5, threshold=0.6)
        assert result is False
        
        # Score 0.5 with threshold 0.4 should be True
        result = filter_obj.should_alert(features, rule_score=0.5, threshold=0.4)
        assert result is True

    @patch("app.ml.filter.CatBoostClassifier")
    def test_predict_proba_with_model(self, mock_catboost_class: MagicMock) -> None:
        """When model is loaded, predict_proba should use model prediction."""
        # Setup mock model - CatBoost returns numpy array
        import numpy as np
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])  # [prob_0, prob_1]
        mock_catboost_class.return_value = mock_model
        
        # Create a fake model file path
        with patch.object(Path, "exists", return_value=True):
            filter_obj = SignalFilter(model_path=Path("/fake/model.cbm"))
            filter_obj.model = mock_model  # Ensure model is set
            
            features = {
                "mid_price": 100.0,
                "spread_bps": 2.0,
                "imbalance": 0.3,
                "microprice": 100.05,
                "microprice_offset_bps": 1.0,
                "buy_volume_3s": 5.0,
                "sell_volume_3s": 2.0,
                "delta_ratio_3s": 0.25,
                "trades_3s": 5.0,
                "trade_intensity": 1.67,
                "volatility_30s": 0.02,
                "book_depth_bid": 6.5,
                "book_depth_ask": 6.0,
            }
            
            result = filter_obj.predict_proba(features, rule_score=0.5)
            # Should return model's predicted probability (0.7)
            assert result == 0.7

    @patch("app.ml.filter.CatBoostClassifier")
    def test_should_alert_with_model_above_threshold(self, mock_catboost_class: MagicMock) -> None:
        """should_alert should return True when model probability >= threshold."""
        import numpy as np
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.2, 0.8]])  # High probability
        mock_catboost_class.return_value = mock_model
        
        with patch.object(Path, "exists", return_value=True):
            filter_obj = SignalFilter(model_path=Path("/fake/model.cbm"))
            filter_obj.model = mock_model
            
            features = {col: 0.5 for col in filter_obj.feature_columns}
            result = filter_obj.should_alert(features, rule_score=0.5, threshold=0.55)
            assert result is True

    @patch("app.ml.filter.CatBoostClassifier")
    def test_should_alert_with_model_below_threshold(self, mock_catboost_class: MagicMock) -> None:
        """should_alert should return False when model probability < threshold."""
        import numpy as np
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.6, 0.4]])  # Low probability
        mock_catboost_class.return_value = mock_model
        
        with patch.object(Path, "exists", return_value=True):
            filter_obj = SignalFilter(model_path=Path("/fake/model.cbm"))
            filter_obj.model = mock_model
            
            features = {col: 0.5 for col in filter_obj.feature_columns}
            result = filter_obj.should_alert(features, rule_score=0.5, threshold=0.55)
            assert result is False

    def test_feature_columns_order(self) -> None:
        """Feature columns should be in expected order."""
        filter_obj = SignalFilter(model_path=Path("/nonexistent/model.cbm"))
        expected_columns = [
            "mid_price", "spread_bps", "imbalance", "microprice", "microprice_offset_bps",
            "buy_volume_3s", "sell_volume_3s", "delta_ratio_3s", "trades_3s", "trade_intensity",
            "volatility_30s", "book_depth_bid", "book_depth_ask",
        ]
        assert filter_obj.feature_columns == expected_columns

    @patch("app.ml.filter.CatBoostClassifier")
    def test_missing_features_use_default(self, mock_catboost_class: MagicMock) -> None:
        """Missing features should default to 0.0."""
        import numpy as np
        mock_model = MagicMock()
        mock_model.predict_proba.return_value = np.array([[0.5, 0.5]])
        mock_catboost_class.return_value = mock_model
        
        with patch.object(Path, "exists", return_value=True):
            filter_obj = SignalFilter(model_path=Path("/fake/model.cbm"))
            filter_obj.model = mock_model
            
            # Empty features dict - all should default to 0.0
            features: dict[str, float] = {}
            filter_obj.predict_proba(features, rule_score=0.5)
            
            # Verify predict_proba was called with zeros + rule_score
            call_args = mock_model.predict_proba.call_args[0][0]
            # Should have 13 features + 1 rule_score = 14 values
            assert len(call_args[0]) == 14


class TestLoadTrainingData:
    """Tests for load_training_data function."""

    def test_load_training_data_joins_alerts_and_trades(self, temp_parquet_dir: Path) -> None:
        """load_training_data should correctly join alerts and trades by alert_id."""
        import pyarrow as pa
        from pyarrow import parquet as pq
        
        # Create test alerts - must have required columns
        alerts_df = pd.DataFrame({
            "alert_id": [1, 2, 3],
            "symbol": ["BTCUSDT", "ETHUSDT", "BTCUSDT"],
            "mid_price": [50000.0, 3000.0, 50000.0],
            "spread_bps": [2.0, 2.0, 2.0],
            "imbalance": [0.3, 0.3, 0.3],
            "microprice": [50000.5, 3000.5, 50000.5],
            "microprice_offset_bps": [1.0, 1.0, 1.0],
            "buy_volume_3s": [5.0, 5.0, 5.0],
            "sell_volume_3s": [2.0, 2.0, 2.0],
            "delta_ratio_3s": [0.25, 0.25, 0.25],
            "trades_3s": [5.0, 5.0, 5.0],
            "trade_intensity": [1.67, 1.67, 1.67],
            "volatility_30s": [0.02, 0.02, 0.02],
            "book_depth_bid": [3.0, 3.0, 3.0],
            "book_depth_ask": [3.0, 3.0, 3.0],
            "score": [0.7, 0.7, 0.7],
        })
        
        # Create test trades
        trades_df = pd.DataFrame({
            "alert_id": [1, 2, 3],
            "pnl": [10.5, -5.0, 0.0],
            "status": ["closed", "closed", "closed"],
            "exit_reason": ["take_profit", "stop_loss", "take_profit"],
        })
        
        # Write parquet files
        pq.write_table(pa.Table.from_pandas(alerts_df), temp_parquet_dir / "alerts_test.parquet")
        pq.write_table(pa.Table.from_pandas(trades_df), temp_parquet_dir / "trades_test.parquet")
        
        from app.ml.train import load_training_data
        
        result = load_training_data(temp_parquet_dir)
        
        assert len(result) == 3
        assert "label" in result.columns
        # Check that pnl was joined correctly
        assert result.loc[result["alert_id"] == 1, "pnl"].iloc[0] == 10.5
        assert result.loc[result["alert_id"] == 2, "pnl"].iloc[0] == -5.0

    def test_load_training_data_creates_label_from_pnl(self, temp_parquet_dir: Path) -> None:
        """label should be 1 if pnl > 0, else 0."""
        import pyarrow as pa
        from pyarrow import parquet as pq
        
        alerts_df = pd.DataFrame({
            "alert_id": [1, 2, 3],
            "symbol": ["BTC", "BTC", "BTC"],
            "mid_price": [50000.0, 50000.0, 50000.0],
            "spread_bps": [2.0, 2.0, 2.0],
            "imbalance": [0.3, 0.3, 0.3],
            "microprice": [50000.5, 50000.5, 50000.5],
            "microprice_offset_bps": [1.0, 1.0, 1.0],
            "buy_volume_3s": [5.0, 5.0, 5.0],
            "sell_volume_3s": [2.0, 2.0, 2.0],
            "delta_ratio_3s": [0.25, 0.25, 0.25],
            "trades_3s": [5.0, 5.0, 5.0],
            "trade_intensity": [1.67, 1.67, 1.67],
            "volatility_30s": [0.02, 0.02, 0.02],
            "book_depth_bid": [3.0, 3.0, 3.0],
            "book_depth_ask": [3.0, 3.0, 3.0],
            "score": [0.7, 0.7, 0.7],
        })
        trades_df = pd.DataFrame({
            "alert_id": [1, 2, 3],
            "pnl": [10.0, -5.0, 0.0],  # positive, negative, zero
            "status": ["closed", "closed", "closed"],
            "exit_reason": ["tp", "sl", "tp"],
        })
        
        pq.write_table(pa.Table.from_pandas(alerts_df), temp_parquet_dir / "alerts_test.parquet")
        pq.write_table(pa.Table.from_pandas(trades_df), temp_parquet_dir / "trades_test.parquet")
        
        from app.ml.train import load_training_data
        
        result = load_training_data(temp_parquet_dir)
        
        # pnl > 0 => label = 1
        assert result.loc[result["alert_id"] == 1, "label"].iloc[0] == 1
        # pnl < 0 => label = 0
        assert result.loc[result["alert_id"] == 2, "label"].iloc[0] == 0
        # pnl == 0 => label = 0
        assert result.loc[result["alert_id"] == 3, "label"].iloc[0] == 0

    def test_load_training_data_filters_unclosed_trades(self, temp_parquet_dir: Path) -> None:
        """Only closed trades should be included in training data."""
        import pyarrow as pa
        from pyarrow import parquet as pq
        
        alerts_df = pd.DataFrame({
            "alert_id": [1, 2, 3, 4],
            "symbol": ["BTC", "BTC", "BTC", "BTC"],
            "mid_price": [50000.0, 50000.0, 50000.0, 50000.0],
            "spread_bps": [2.0, 2.0, 2.0, 2.0],
            "imbalance": [0.3, 0.3, 0.3, 0.3],
            "microprice": [50000.5, 50000.5, 50000.5, 50000.5],
            "microprice_offset_bps": [1.0, 1.0, 1.0, 1.0],
            "buy_volume_3s": [5.0, 5.0, 5.0, 5.0],
            "sell_volume_3s": [2.0, 2.0, 2.0, 2.0],
            "delta_ratio_3s": [0.25, 0.25, 0.25, 0.25],
            "trades_3s": [5.0, 5.0, 5.0, 5.0],
            "trade_intensity": [1.67, 1.67, 1.67, 1.67],
            "volatility_30s": [0.02, 0.02, 0.02, 0.02],
            "book_depth_bid": [3.0, 3.0, 3.0, 3.0],
            "book_depth_ask": [3.0, 3.0, 3.0, 3.0],
            "score": [0.7, 0.7, 0.7, 0.7],
        })
        trades_df = pd.DataFrame({
            "alert_id": [1, 2, 3, 4],
            "pnl": [10.0, -5.0, 15.0, 20.0],
            "status": ["closed", "open", "pending", "closed"],  # Only 1 and 4 are closed
            "exit_reason": ["tp", None, None, "sl"],
        })
        
        pq.write_table(pa.Table.from_pandas(alerts_df), temp_parquet_dir / "alerts_test.parquet")
        pq.write_table(pa.Table.from_pandas(trades_df), temp_parquet_dir / "trades_test.parquet")
        
        from app.ml.train import load_training_data
        
        result = load_training_data(temp_parquet_dir)
        
        # Only alert_id 1 and 4 should be included (closed trades)
        assert len(result) == 2
        assert set(result["alert_id"].tolist()) == {1, 4}

    def test_load_training_data_raises_when_no_files(self, temp_parquet_dir: Path) -> None:
        """Should raise ValueError when no parquet files found."""
        from app.ml.train import load_training_data
        
        with pytest.raises(ValueError, match="No training data found"):
            load_training_data(temp_parquet_dir)

    def test_load_training_data_drops_nan_labels(self, temp_parquet_dir: Path) -> None:
        """Rows with NaN labels should be dropped."""
        import pyarrow as pa
        from pyarrow import parquet as pq
        
        alerts_df = pd.DataFrame({"alert_id": [1, 2], "symbol": ["BTC", "BTC"]})
        trades_df = pd.DataFrame({
            "alert_id": [1, 2],
            "pnl": [10.0, None],  # None will create NaN label
            "status": ["closed", "closed"],
            "exit_reason": ["tp", "sl"],
        })
        
        pq.write_table(pa.Table.from_pandas(alerts_df), temp_parquet_dir / "alerts_test.parquet")
        pq.write_table(pa.Table.from_pandas(trades_df), temp_parquet_dir / "trades_test.parquet")
        
        from app.ml.train import load_training_data
        
        result = load_training_data(temp_parquet_dir)
        
        # Only row with valid pnl should remain
        assert len(result) == 1
        assert result["alert_id"].iloc[0] == 1
