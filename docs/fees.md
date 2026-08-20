# Fees and trading costs

Fees are account-specific. The app must use the account's actual maker/taker rate when account API access is added, rather than relying on a permanent hardcoded number.

## Sources checked

- [Bybit trading fee structure](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure/): the published base table currently lists VIP 0 spot maker/taker at 0.1000% / 0.1000% and perpetual/futures maker/taker at 0.0200% / 0.0550%. The page explicitly warns that actual rates can vary by region and directs users to their account fee page.
- [Bybit Get Fee Rate API](https://bybit-exchange.github.io/docs/v5/account/fee-rate): authenticated `GET /v5/account/fee-rate` returns `makerFeeRate` and `takerFeeRate` for `spot`, `linear`, `inverse`, and `option`.
- [Binance fee page](https://www.binance.com/en/fee/trading): the currently published regular spot row lists 0.100% / 0.100% before applicable discounts; VIP level, BNB discounts, product, region, and promotions change the result.
- [Tiger.com pricing](https://www.tiger.com/terminal/prices): Tiger.com is a terminal/license product. The exchange's trading fee is separate from the terminal license or any broker/referral program.

## Paper accounting

For a round trip the baseline is:

```text
gross_pnl
- entry trading fee
- exit trading fee
- estimated slippage on both legs
- funding for the holding interval
- any contract-specific costs
= net_pnl
```

The first paper default uses `PAPER_FEE_RATE=0.00055`, matching the published Bybit VIP 0 linear taker rate as a conservative market-order baseline. This is only a placeholder until the account's exact rate is fetched and stored. For spot or a different exchange, configure a different rate.

Funding is not a trading commission. For perpetuals it is periodic and depends on the instrument and interval; it must be captured from the exchange stream/REST endpoint at the time of a paper position. Withdrawal, deposit, conversion, liquidation, and broker-program costs are separate and should not be silently folded into trading fees.
