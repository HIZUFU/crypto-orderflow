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


def generate_signal(
    symbol: str,
    features: dict[str, float],
    notional: float = 50.0,
    leverage: int = 1,
    risk_pct: float = 0.0015,
    reward_risk_ratio: float = 2.0,
) -> Signal | None:
    """Generate a transparent order-flow candidate; this is not a calibrated probability."""
    del leverage
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
        evidence = "bid pressure, positive trade delta and bullish microprice"
    elif imbalance <= -0.22 and delta <= -0.18 and offset < 0:
        direction, score = "SHORT", min(short_score, 0.99)
        evidence = "ask pressure, negative trade delta and bearish microprice"
    else:
        return None

    risk_pct = max(risk_pct, 0.0001)
    entry_band = mid * 0.00025
    reward_pct = risk_pct * max(reward_risk_ratio, 1.0)
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
        reason=(
            f"{evidence}; imbalance={imbalance:.3f}, delta_3s={delta:.3f}, "
            f"microprice_offset={offset:.2f}bps, spread={spread:.2f}bps"
        ),
        features=features,
    )
