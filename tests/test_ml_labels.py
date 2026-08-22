from datetime import datetime, timezone
from types import SimpleNamespace

from app.ml.labels import label_summary, labeled_alert_rows


def item(**values):
    return SimpleNamespace(**values)


def test_all_measured_alerts_become_training_labels() -> None:
    alerts = [
        item(id=1, position_notional=100.0),
        item(id=2, position_notional=100.0),
        item(id=3, position_notional=100.0),
    ]
    trades = [item(alert_id=1, status="closed", pnl=2.5, closed_at=datetime.now(timezone.utc), opened_at=datetime.now(timezone.utc))]
    outcomes = [
        item(alert_id=2, outcome_type="expired", hypothetical_pnl=-1.0, outcome_timestamp=datetime.now(timezone.utc)),
    ]
    rows = labeled_alert_rows(alerts, outcomes, trades, paper_fee_rate=0.001)
    assert [(row["alert"].id, row["label_source"], row["label"]) for row in rows] == [
        (1, "paper_trade", 1),
        (2, "expiry_mark", 0),
    ]
    summary = label_summary(rows, total_alerts=3)
    assert summary["labeled_alerts"] == 2
    assert summary["unlabeled_alerts"] == 1


def test_expiry_label_includes_estimated_round_trip_fees() -> None:
    alert = item(id=1, position_notional=100.0)
    outcome = item(alert_id=1, outcome_type="expired", hypothetical_pnl=0.1, outcome_timestamp=datetime.now(timezone.utc))
    row = labeled_alert_rows([alert], [outcome], [], paper_fee_rate=0.001)[0]
    assert row["pnl"] == -0.1
    assert row["label"] == 0
