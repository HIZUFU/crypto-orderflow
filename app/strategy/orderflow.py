from dataclasses import dataclass


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str
    entry_low: float
    entry_high: float
    reference_price: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    score: float
    reason: str
    features: dict[str, float]


def generate_signal(symbol: str, features: dict[str, float], notional: float = 10.0, leverage: int = 1) -> Signal | None:
    """Transparent research rule; thresholds must be validated out of sample."""
    del leverage  # Leverage changes margin, not the price risk of a fixed notional.
    imbalance = features["imbalance"]
    delta = features["delta_ratio_3s"]
    spread = features["spread_bps"]
    offset = features["microprice_offset_bps"]
    mid = features["mid_price"]

    if spread <= 0 or spread > 8 or features["trades_3s"] < 2:
        return None

    long_score = 0.5 + max(imbalance, 0.0) * 0.35 + max(delta, 0.0) * 0.25 + max(offset, 0.0) / 100 * 0.10
    short_score = 0.5 + max(-imbalance, 0.0) * 0.35 + max(-delta, 0.0) * 0.25 + max(-offset, 0.0) / 100 * 0.10

    if imbalance >= 0.22 and delta >= 0.18 and offset > 0:
        direction, score = "LONG", min(long_score, 0.99)
    elif imbalance <= -0.22 and delta <= -0.18 and offset < 0:
        direction, score = "SHORT", min(short_score, 0.99)
    else:
        return None

    entry_band = mid * 0.00025
    risk_pct = 0.0015
    reward_pct = 0.0030
    if direction == "LONG":
        stop = mid * (1 - risk_pct)
        target = mid * (1 + reward_pct)
    else:
        stop = mid * (1 + risk_pct)
        target = mid * (1 - reward_pct)

    return Signal(
        symbol=symbol,
        direction=direction,
        entry_low=mid - entry_band,
        entry_high=mid + entry_band,
        reference_price=mid,
        stop_loss=stop,
        take_profit=target,
        risk_amount=notional * risk_pct,
        score=score,
        reason=f"imbalance={imbalance:.3f}, delta_3s={delta:.3f}, microprice_offset={offset:.2f}bps",
        features=features,
    )
