from typing import cast

import numpy as np
import pandas as pd

from .schemas import AssetType
from .utils import check_data_dir, load_ticker_data, parse_date


class Prices:
    """Class to load prices for a given ticker and date range.
    Raw prices are loaded and backfilled to the start and end dates.
    For stocks and options adjusted prices are calculated using the
    backfilled prices and the split and dividend data.
    """

    def __init__(self, data_dir: str, debug: bool = False) -> None:
        self.debug = debug
        self.data_dir, self.asset_types = check_data_dir(data_dir)

    def get_prices(
        self, ticker: str, date_start: str | None = None, date_end: str | None = None
    ) -> pd.DataFrame:
        """Get prices for a given ticker and date range."""
        df, asset_type = self.load_prices(ticker, date_start, date_end)
        df = self.adjust_prices(df, asset_type)
        return df

    def load_prices(
        self, ticker: str, date_start: str | None = None, date_end: str | None = None
    ) -> tuple[pd.DataFrame, AssetType]:
        """Load prices for a given ticker and date range."""
        print(f"⛏️  Loading {ticker} price data...")
        df, asset_type = load_ticker_data(
            self.data_dir, self.asset_types, ticker, date_start, date_end
        )
        if "window_start" not in df.columns:
            raise ValueError(f"No window_start column found in data for ticker: `{ticker}`")

        df["timestamp"] = pd.to_datetime(df["window_start"], unit="ns")
        df = df.sort_values("timestamp").set_index("timestamp")
        df = pd.DataFrame(df[["close"]]).rename(columns={"close": ticker})

        if self.debug:
            start_date = parse_date(cast(pd.Timestamp, df.index[0]))
            end_date = parse_date(cast(pd.Timestamp, df.index[-1]))
            print(
                f"🗑️  Loaded {len(df):,} price records for {ticker} "
                f"from {start_date} to {end_date}:"
                f"\n{'-' * 32}\n{df.head(5)}\n{'-' * 32}"
            )

        return df, asset_type

    def adjust_prices(self, df: pd.DataFrame, asset_type: AssetType) -> pd.DataFrame:
        """Adjust prices for a given asset type via the following steps:
        1. Backfill the missing prices
        2. Adjust for splits
        3. Adjust for dividends
        """
        print(f"⚙️  Adjusting {df.columns[0]} price data...")
        df = self.backfill_prices(df)
        df = self.adjust_splits(df, asset_type)
        df = self.adjust_dividends(df, asset_type)
        return df

    def backfill_prices(self, df: pd.DataFrame) -> pd.DataFrame:
        """Backfill the missing price values and fill in missing rows.
        Creates a complete 1-minute timestamp range from the first to last timestamp,
        then uses exponential interpolation to fill in gaps via log -> linear interpolate -> exp
        """
        col, num_rows = df.columns[0], len(df)
        df = df.reindex(pd.date_range(start=df.index[0], end=df.index[-1], freq="1min"))
        df[col] = df[col].apply(np.log).interpolate(method="linear").apply(np.exp).ffill().bfill()
        if self.debug and len(df) > num_rows:
            print(f"🔧 Backfilled {len(df) - num_rows:,} new rows")
        df.index.name = "timestamp"
        return df

    def adjust_splits(self, df: pd.DataFrame, asset_type: AssetType) -> pd.DataFrame:
        """Adjust for historical prices for stock splits/merges."""
        if asset_type not in [AssetType.STOCKS, AssetType.OPTIONS]:
            if self.debug:
                print(f"🪚  Not adjusting {asset_type} assets for splits/merges")
            return df
        else:
            print(f"🪚  Adjusting for splits/merges is not yet implemented")
            return df

    def adjust_dividends(self, df: pd.DataFrame, asset_type: AssetType) -> pd.DataFrame:
        """Adjust for historical prices for stock dividends."""
        if asset_type != AssetType.STOCKS:
            if self.debug:
                print(f"🔩 Not adjusting {asset_type} assets for dividends")
            return df
        else:
            print(f"🔩 Adjusting for dividends is not yet implemented")
            return df
