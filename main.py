import argparse
import sys
from typing import get_args

from src import Prices, save_if_valid, save_options_if_valid
from src.constants import (
    CHECKS_CONFIG,
    DEFAULT_DATA_DIR,
    DEFAULT_DATE_END,
    DEFAULT_DATE_START,
    DEFAULT_FORMAT,
    DEFAULT_SAVE_DIR,
    OPTIONS_CHECKS_CONFIG,
    SHOW_PLOT,
)
from src.schemas import AssetType, PriceFileFormat
from src.utils import parsable_date


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Adjust raw asset prices for a single ticker.")
    p.add_argument("ticker", type=str.upper, help="Ticker symbol, e.g. BTC-USD")
    p.add_argument("--format", choices=list(get_args(PriceFileFormat)), default=DEFAULT_FORMAT)
    p.add_argument("--date-start", type=parsable_date, default=DEFAULT_DATE_START)
    p.add_argument("--date-end", type=parsable_date, default=DEFAULT_DATE_END)
    p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    p.add_argument("--save-dir", default=DEFAULT_SAVE_DIR)
    # Mutually exclusive: a dividend-adjusted underlying can't align with the (never
    # dividend-adjusted) options, so passing both errors at parse time, before any retrieval.
    adjust = p.add_mutually_exclusive_group()
    adjust.add_argument(
        "--dividends",
        action="store_true",
        help="Back-adjust the stock series for cash dividends (Adj-Close-style total return). "
        "Off by default — the output is the actual split-adjusted traded price. Mutually "
        "exclusive with --options.",
    )
    adjust.add_argument(
        "--options",
        action="store_true",
        help="Also load + backfill + split-unify + structural-gate + save all option "
        "contracts on the underlying (the underlying is saved split-only, aligned with the "
        "options), after the underlying's stocks pass succeeds. Aborts if either pass fails. "
        "Mutually exclusive with --dividends.",
    )
    return p.parse_args()


def _print_options_summary(label: str, df) -> None:
    if df.empty:
        print(f"   {label}: 0 bars / 0 contracts")
        return
    ts = df.index.get_level_values("timestamp_utc")
    n_contracts = df.index.get_level_values("ticker").nunique()
    print(f"   {label}: {len(df):,} bars / {n_contracts:,} contracts " f"({ts.min()} → {ts.max()})")


if __name__ == "__main__":
    args = parse_args()

    prices = Prices(data_dir=args.data_dir)

    if args.options:
        # Retrieve the options for the ticker plus its (split-only) underlying in one call.
        underlying, calls, puts = prices.options.get_options(
            args.ticker, date_start=args.date_start, date_end=args.date_end
        )
        if not save_if_valid(
            underlying,
            save_dir=args.save_dir,
            format=args.format,
            config=CHECKS_CONFIG,
            asset_type=AssetType.STOCKS,
            show_plot=SHOW_PLOT,
            dividends_adjusted=False,
        ):
            print(f"❌ {args.ticker} stock price failed verification -- aborting options pass!")
            sys.exit(1)
        print(f"\n🗃️  Option contracts for {args.ticker}:")
        _print_options_summary("calls", calls)
        _print_options_summary("puts", puts)
        if not save_options_if_valid(
            calls,
            puts,
            underlying=args.ticker,
            underlying_df=underlying,
            save_dir=args.save_dir,
            format=args.format,
            config=OPTIONS_CHECKS_CONFIG,
        ):
            sys.exit(1)
    else:
        df, asset_type = prices.asset.get_prices(
            ticker=args.ticker,
            date_start=args.date_start,
            date_end=args.date_end,
            dividends=args.dividends,
        )
        save_if_valid(
            df,
            save_dir=args.save_dir,
            format=args.format,
            config=CHECKS_CONFIG,
            asset_type=asset_type,
            show_plot=SHOW_PLOT,
            dividends_adjusted=args.dividends,
        )
