"""Build unbiased training labels from measured alert outcomes."""
from collections import defaultdict
from typing import Iterable

from app.db.models import Alert, AlertOutcome, PaperTrade


def labeled_alert_rows(
    alerts: Iterable[Alert],
    outcomes: Iterable[AlertOutcome],
    trades: Iterable[PaperTrade],
    paper_fee_rate: float,
) -> list[dict]:
    """Return one label per alert only when its result is already observable."""
    outcomes_by_alert: dict[int, list[AlertOutcome]] = defaultdict(list)
    trades_by_alert: dict[int, list[PaperTrade]] = defaultdict(list)
    for outcome in outcomes:
        outcomes_by_alert[outcome.alert_id].append(outcome)
    for trade in trades:
        trades_by_alert[trade.alert_id].append(trade)

    rows: list[dict] = []
    for alert in alerts:
        closed = sorted(
            (trade for trade in trades_by_alert[alert.id] if trade.status == "closed" and trade.pnl is not None),
            key=lambda trade: trade.closed_at or trade.opened_at,
            reverse=True,
        )
        if closed:
            pnl = float(closed[0].pnl)
            label_source = "paper_trade"
        else:
            marked = sorted(
                (
                    outcome
                    for outcome in outcomes_by_alert[alert.id]
                    if outcome.outcome_type == "expired" and outcome.hypothetical_pnl is not None
                ),
                key=lambda outcome: outcome.outcome_timestamp,
                reverse=True,
            )
            if not marked:
                continue
            # Expiry mark is stored before fees; make its label comparable to paper PnL.
            pnl = float(marked[0].hypothetical_pnl) - alert.position_notional * paper_fee_rate * 2
            label_source = "expiry_mark"
        rows.append({
            "alert": alert,
            "pnl": pnl,
            "label": int(pnl > 0),
            "label_source": label_source,
        })
    return rows


def label_summary(rows: Iterable[dict], total_alerts: int) -> dict[str, int]:
    values = list(rows)
    return {
        "total_alerts": total_alerts,
        "labeled_alerts": len(values),
        "paper_trade_labels": sum(row["label_source"] == "paper_trade" for row in values),
        "expiry_mark_labels": sum(row["label_source"] == "expiry_mark" for row in values),
        "winning_labels": sum(row["label"] == 1 for row in values),
        "losing_labels": sum(row["label"] == 0 for row in values),
        "unlabeled_alerts": total_alerts - len(values),
    }
