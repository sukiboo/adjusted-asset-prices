import os

import pandas as pd

from src import Prices, check_prices


def save_prices(df: pd.DataFrame, save_dir: str = "./data/prices") -> None:
    """Save the prices to a CSV file."""
    ticker = df.columns[0]
    save_path = f"{save_dir}/{ticker}.csv"
    os.makedirs(save_dir, exist_ok=True)
    df.to_csv(save_path, index=True)
    print(f"💾 Saved {ticker} prices to {save_path}")


def load_prices(ticker: str, load_dir: str = "./data/prices") -> pd.DataFrame:
    """Load prices from a CSV file."""
    load_path = f"{load_dir}/{ticker}.csv"
    if not os.path.exists(load_path):
        raise FileNotFoundError(f"Price file not found: {load_path}")
    try:
        df = pd.read_csv(load_path, index_col=0, parse_dates=True)
        df.index.name = "timestamp"
        return df
    except Exception as e:
        raise RuntimeError(f"Failed to load prices from {load_path}: {e}") from e


if __name__ == "__main__":
    prices = Prices(data_dir="./data/files", debug=True)
    df = prices.get_prices(ticker="BTC-USD", date_start="2025-01-01", date_end=None)
    if check_prices(df):
        print("\n🎉 All checks passed, saving the price data...")
        save_prices(df, save_dir="./data/prices")
    else:
        print("\n❌ Some checks failed, not saving the price data!")
