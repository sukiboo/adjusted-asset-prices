import io
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

from src import Prices, check_prices
from src.constants import CHECKS_CONFIG, DEFAULT_DATA_DIR
from src.schemas import AssetType, ChecksConfig

CHECKS_CONFIG_NO_PLOT: ChecksConfig = {**CHECKS_CONFIG, "show_plot": False}


@pytest.fixture(scope="session")
def data_dir() -> Path:
    p = Path(DEFAULT_DATA_DIR).expanduser().resolve()
    if not p.is_dir():
        pytest.skip(f"Data directory {p} does not exist.")
    return p


def require_asset_data(data_dir: Path, asset_type: AssetType) -> None:
    sub = data_dir / asset_type
    if not (sub.is_dir() and any(sub.glob("*.csv.gz"))):
        pytest.skip(f"No raw {asset_type} files at {sub}.")


def describe(df: pd.DataFrame, ticker: str) -> None:
    print(
        "\n"
        f"🔎 {ticker}: {len(df):,} values from {df.index[0]} to {df.index[-1]},"
        f" price ranges from ${df[ticker].min():,.2f} to ${df[ticker].max():,.2f}"
    )


@contextmanager
def quiet_output(keep_substrs: tuple[str, ...] = ()) -> Iterator[None]:
    # Capture stdout for the duration of the block. On exit:
    # - success: re-emit only lines containing one of keep_substrs.
    # - exception: dump the full capture so failures stay diagnosable inline.
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        sys.stdout = old_stdout
        captured = buf.getvalue()
        if failed:
            sys.stdout.write(captured)
            sys.stdout.flush()
        elif keep_substrs:
            for line in captured.splitlines():
                if any(s in line for s in keep_substrs):
                    print(line)


def quiet_get(
    prices: Prices, ticker: str, date_start: str, date_end: str
) -> tuple[pd.DataFrame, AssetType]:
    with quiet_output():
        return prices.get_prices(ticker=ticker, date_start=date_start, date_end=date_end)


def quiet_check(df: pd.DataFrame, asset_type: AssetType) -> bool:
    with quiet_output(("Price comparison",)):
        return check_prices(df, config=CHECKS_CONFIG_NO_PLOT, asset_type=asset_type)
