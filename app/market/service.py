from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionSpec:
    id: int | None
    label: str
    provider: str
    market_type: str
    ws_url: str | None
    symbols: tuple[str, ...]

    @property
    def identity(self) -> str:
        return str(self.id) if self.id is not None else f"env-{self.provider}-{self.market_type}"


def default_ws_url(provider: str, market_type: str) -> str:
    if provider == "bybit":
        return "wss://stream.bybit.com/v5/public/spot" if market_type == "spot" else "wss://stream.bybit.com/v5/public/linear"
    if provider == "binance":
        return "wss://stream.binance.com:9443/stream" if market_type == "spot" else "wss://fstream.binance.com/stream"
    raise ValueError(f"Unsupported provider: {provider}")


class MarketService:
    def __init__(self, settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory
        self.sources = {}
        self.books = {}
        self.engines = {}
        self.candles = {}
        self.latest = {}
        self.last_signal_at = {}
        self.ml_filter = None
        self.refresh_ml_filter()
        self._tasks = []
        self._task = None
        self._monitor_task = None
        self._outcome_task = None
        self._stop = asyncio.Event()

    @property
    def stream_connected(self) -> bool:
        return any(not task.done() for task in self._tasks)

    def refresh_ml_filter(self) -> None:
        """Apply a runtime ML toggle without restarting public streams."""
        self.ml_filter = None
        if not self.settings.use_ml_filter:
            return
        try:
            candidate = SignalFilter(self.settings.model_path)
            self.ml_filter = candidate
            logger.info("CatBoost filter %s", "loaded" if candidate.model else "not available")
        except Exception:
            logger.exception("Could not load CatBoost filter")

    async def _load_specs(self) -> list[ConnectionSpec]:
        async with self.session_factory() as session:
            rows = list((await session.execute(select(ExchangeConnection))).scalars())
        if not rows:
            ws_url = self.settings.bybit_ws_url if self.settings.default_exchange == "bybit" else self.settings.binance_ws_url
            return [ConnectionSpec(
                None, f"{self.settings.default_exchange.title()} default",
                self.settings.default_exchange, "linear", ws_url,
                tuple(self.settings.tracked_symbols),
            )]
        specs: list[ConnectionSpec] = []
        for row in rows:
            if not row.enabled:
                continue
            try:
                symbols = tuple(
                    str(symbol).strip().upper()
                    for symbol in json.loads(row.symbols_json or "[]")
                    if str(symbol).strip()
                )
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed symbol list on connection %s", row.id)
                symbols = ()
            if symbols:
                specs.append(ConnectionSpec(
                    row.id, row.label, row.provider, row.market_type, row.ws_url, symbols
                ))
        return specs

    def _prepare_sources(self, specs: list[ConnectionSpec]) -> None:
        self.sources.clear()
        self.books.clear()
        self.engines.clear()
        self.candles.clear()
        self.latest.clear()
        self.last_signal_at.clear()
        for spec in specs:
            for symbol in spec.symbols:
                source_key = f"{spec.identity}:{symbol}"
                self.sources[source_key] = {
                    "source_key": source_key,
                    "connection_id": spec.id,
                    "exchange": spec.provider,
                    "market": spec.market_type,
                    "label": spec.label,
                    "symbol": symbol,
                }
                self.books[source_key] = LocalOrderBook()
                self.engines[source_key] = FeatureEngine(self.books[source_key])
                self.candles[source_key] = CandleAggregator(symbol)

    async def start(self) -> None:
        specs = await self._load_specs()
        self._prepare_sources(specs)
        self._stop = asyncio.Event()
        self._tasks = [
            asyncio.create_task(self._run_source(spec), name=f"market-{spec.identity}")
            for spec in specs
        ]
        self._task = asyncio.create_task(self._wait_streams(), name="market-stream-group")
        if self.settings.enable_auto_close:
            self._monitor_task = asyncio.create_task(self._monitor_positions(), name="position-monitor")
        self._outcome_task = asyncio.create_task(
            self._monitor_alert_outcomes(), name="alert-outcome-monitor"
        )

    async def stop(self) -> None:
        self._stop.set()
        tasks = [*self._tasks, self._task, self._monitor_task, self._outcome_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*[task for task in tasks if task], return_exceptions=True)
        self._tasks = []
        self._task = self._monitor_task = self._outcome_task = None

    async def reload_connections(self) -> None:
        await self.stop()
        await self.start()

    async def _wait_streams(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_source(self, spec: ConnectionSpec) -> None:
        ws_url = spec.ws_url or default_ws_url(spec.provider, spec.market_type)
        while not self._stop.is_set():
            try:
                exchange = get_exchange(
                    spec.provider, ws_url=ws_url, depth=self.settings.orderbook_depth,
                    market_type=spec.market_type,
                )
                async for update in exchange.subscribe(list(spec.symbols)):
                    if self._stop.is_set():
                        return
                    source_key = f"{spec.identity}:{update.symbol.upper()}"
                    if source_key not in self.sources:
                        continue
                    if hasattr(update, "bids"):
                        self.books[source_key].apply(
                            "snapshot" if update.is_snapshot else "delta",
                            update.bids, update.asks, update.update_id, update.timestamp_ms,
                        )
                        features = self.engines[source_key].calculate()
                        if features is not None:
                            self.latest[source_key] = features
                            await self._maybe_alert(spec, source_key, features)
                    elif hasattr(update, "price"):
                        event = TradeEvent(
                            update.timestamp_ms, update.price, update.quantity, update.side
                        )
                        self.engines[source_key].observe_trade(event)
                        self.candles[source_key].add_trade(
                            event.timestamp_ms, event.price, event.quantity
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("stream failed for %s; reconnecting", spec.label)
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.reconnect_delay_seconds
                    )
                except asyncio.TimeoutError:
                    pass

    async def _maybe_alert(self, spec, source_key, features):
        now = monotonic()
        if now - self.last_signal_at.get(source_key, 0.0) < self.settings.signal_cooldown_seconds:
            return
        signal = generate_signal(
            self.sources[source_key]["symbol"], features,
            notional=self.settings.paper_notional_usdt,
            leverage=self.settings.paper_leverage,
            risk_value=self.settings.risk_value,
            risk_mode=self.settings.risk_mode,
            reward_risk_ratio=self.settings.reward_risk_ratio,
        )
        if signal is None:
            return
        ml_probability = None
        ml_passed = False
        if self.ml_filter and self.ml_filter.model:
            ml_probability = self.ml_filter.predict_proba(features, signal.score)
            ml_passed = ml_probability >= self.settings.ml_threshold
            if not ml_passed:
                logger.debug(
                    "CatBoost rejected %s %s at %.3f",
                    source_key, signal.direction, ml_probability,
                )
                return
        self.last_signal_at[source_key] = now
        created = utc_now()
        async with self.session_factory() as session:
            session.add(Alert(
                created_at=created,
                expires_at=created + timedelta(seconds=self.settings.signal_ttl_seconds),
                symbol=self.sources[source_key]["symbol"],
                market=spec.market_type,
                exchange=spec.provider,
                source_key=source_key,
                connection_id=spec.id,
                direction=signal.direction,
                entry_low=signal.entry_low,
                entry_high=signal.entry_high,
                reference_price=signal.reference_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                position_notional=self.settings.paper_notional_usdt,
                leverage=signal.leverage if hasattr(signal, "leverage") else self.settings.paper_leverage,
                risk_amount=signal.risk_amount,
                score=signal.score,
                reason=signal.reason,
                features_json=json.dumps(signal.features),
                ml_probability=ml_probability,
                ml_passed_filter=ml_passed,
            ))
            await session.commit()
        logger.info("alert %s %s %s score=%.3f", source_key, signal.direction, signal.score)

    def resolve_source(self, symbol: str, source_key: str | None = None) -> str | None:
        symbol = symbol.upper()
        if source_key is not None:
            return source_key if source_key in self.sources else None
        return next((key for key, info in self.sources.items() if info["symbol"] == symbol), None)

    async def _monitor_positions(self) -> None:
        while not self._stop.is_set():
            try:
                await self._check_positions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("position monitor error")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.position_monitor_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def _check_positions(self) -> None:
        async with self.session_factory() as session:
            trades = list((await session.execute(
                select(PaperTrade).where(PaperTrade.status == "open")
            )).scalars())
            for trade in trades:
                source_key = self.resolve_source(trade.symbol, trade.source_key)
                current = (self.latest.get(source_key) or {}).get("mid_price") if source_key else None
                if current is None:
                    continue
                reason = None
                if trade.direction == "LONG":
                    if current <= trade.stop_loss:
                        reason = "stop_loss"
                    elif current >= trade.take_profit:
                        reason = "take_profit"
                elif current >= trade.stop_loss:
                    reason = "stop_loss"
                elif current <= trade.take_profit:
                    reason = "take_profit"
                if reason:
                    gross = ((current - trade.entry_price) / trade.entry_price) * trade.notional
                    if trade.direction == "SHORT":
                        gross *= -1
                    trade.fees = trade.notional * self.settings.paper_fee_rate * 2
                    trade.pnl = gross - trade.fees
                    trade.exit_price = current
                    trade.exit_reason = reason
                    trade.closed_at = utc_now()
                    trade.status = "closed"
                    alert = await session.get(Alert, trade.alert_id)
                    if alert:
                        alert.outcome_type = reason
                        session.add(AlertOutcome(
                            alert_id=alert.id, paper_trade_id=trade.id,
                            outcome_type=reason, outcome_timestamp=trade.closed_at,
                            price_at_outcome=current, ml_probability=alert.ml_probability,
                            ml_passed_filter=alert.ml_passed_filter,
                        ))
            await session.commit()

    async def _monitor_alert_outcomes(self) -> None:
        while not self._stop.is_set():
            try:
                await self._check_expired_alerts()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("alert outcome monitor error")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.outcome_monitor_interval_seconds
                )
            except asyncio.TimeoutError:
                pass

    async def _check_expired_alerts(self) -> None:
        now = utc_now()
        async with self.session_factory() as session:
            alerts = list((await session.execute(select(Alert).where(
                Alert.expires_at < now, Alert.outcome_type == "pending"
            ))).scalars())
            for alert in alerts:
                alert.outcome_type = "expired"
                source_key = self.resolve_source(alert.symbol, alert.source_key)
                current = (self.latest.get(source_key) or {}).get("mid_price") if source_key else None
                hypothetical = None
                reached_target = None
                hit_stop = None
                if current is not None:
                    hypothetical = ((current - alert.reference_price) / alert.reference_price) * alert.position_notional
                    if alert.direction == "SHORT":
                        hypothetical *= -1
                    reached_target = current >= alert.take_profit if alert.direction == "LONG" else current <= alert.take_profit
                    hit_stop = current <= alert.stop_loss if alert.direction == "LONG" else current >= alert.stop_loss
                session.add(AlertOutcome(
                    alert_id=alert.id, outcome_type="expired", outcome_timestamp=now,
                    price_at_outcome=current, hypothetical_pnl=hypothetical,
                    reached_target=reached_target, hit_stop=hit_stop,
                    ml_probability=alert.ml_probability, ml_passed_filter=alert.ml_passed_filter,
                ))
            await session.commit()
