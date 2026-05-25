from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from src import Prices
from src.schemas import AssetType
from tests.conftest import quiet_check_options, quiet_get_options, require_asset_data


@pytest.fixture(scope="module")
def options_prices(data_dir: Path) -> Prices:
    require_asset_data(data_dir, AssetType.OPTIONS)
    require_asset_data(data_dir, AssetType.STOCKS)  # underlying reference for the gate
    return Prices(data_dir=str(data_dir))


def _tickers(df: pd.DataFrame) -> set[str]:
    return set(df.index.get_level_values("ticker"))


def _contract_close_at(df: pd.DataFrame, ticker: str, et_date: str) -> float:
    series = df.xs(ticker, level="ticker")["close"]
    et_index = series.index.tz_convert("America/New_York")  # type: ignore[attr-defined]
    target = pd.Timestamp(et_date).date()
    mask = (et_index.date == target) & (et_index.hour == 15) & (et_index.minute == 59)
    bars = series[mask]
    assert len(bars) == 1, f"expected one 15:59 ET bar for {ticker} on {et_date}, got {len(bars)}"
    return float(bars.iloc[0])


def _describe_options(calls: pd.DataFrame, puts: pd.DataFrame, underlying: str) -> None:
    n_calls = calls.index.get_level_values("ticker").nunique() if not calls.empty else 0
    n_puts = puts.index.get_level_values("ticker").nunique() if not puts.empty else 0
    print(
        f"\n🔎 {underlying} options: {len(calls):,} call bars / {n_calls:,} contracts, "
        f"{len(puts):,} put bars / {n_puts:,} contracts"
    )


def _busiest_spanning_call(calls: pd.DataFrame, pre_date: str, post_date: str) -> str | None:
    # A call with a 15:59 ET bar on both dates spans the split (the pre-date bar is the
    # relabeled/÷ratio'd pre-split print, the post-date bar is native post-split). Derived
    # generically so the test doesn't hardcode a strike that may not have traded.
    ts_level = cast(pd.DatetimeIndex, calls.index.get_level_values("timestamp_utc"))
    et_index = ts_level.tz_convert("America/New_York")
    tickers = calls.index.get_level_values("ticker")

    def day_tickers(d: str) -> set[str]:
        mask = (
            (et_index.date == pd.Timestamp(d).date())
            & (et_index.hour == 15)
            & (et_index.minute == 59)
        )
        return set(tickers[mask])

    common = day_tickers(pre_date) & day_tickers(post_date)
    if not common:
        return None
    return str(tickers[tickers.isin(common)].value_counts().index[0])


@pytest.mark.integration
def test_nvda_2024_split(options_prices: Prices) -> None:
    # NVDA 10:1 split ex-date 2024-06-10 (clean strikes). The pre-split $1150 call
    # O:NVDA240621C01150000 back-adjusts to the $115 successor O:NVDA240621C00115000
    # (premium ÷10). Across the split boundary the successor's close-to-close ratio is
    # ~1 (continuous), not ~10 (the raw, unadjusted ratio). The structural gate then
    # validates no-arb self-consistency over the full window. (NVDA also split 4:1 in
    # 2021, but that's before this window, so only the 10:1 applies here.)
    calls, puts, ref = quiet_get_options(options_prices, "NVDA", "2024-06-06", "2024-06-12")
    _describe_options(calls, puts, "NVDA")

    succ = "O:NVDA240621C00115000"
    assert succ in _tickers(calls), f"{succ} (÷10 successor) missing from output"
    pre = _contract_close_at(calls, succ, "2024-06-07")
    post = _contract_close_at(calls, succ, "2024-06-10")
    ratio = pre / post
    print(f"🪚  NVDA {succ}: pre=${pre:.4f}, post=${post:.4f}, ratio={ratio:.4f} (raw ~10)")
    assert 0.5 < ratio < 2.0, f"split-adjusted call continuity ratio {ratio:.3f} (expected ~1)"

    assert quiet_check_options(calls, puts, "NVDA", ref)


@pytest.mark.integration
def test_aapl_2014_split_suffixed_root(options_prices: Prices) -> None:
    # AAPL 7:1 split ex-date 2014-06-09 — the canonical non-clean / OCC-suffixed-root case.
    # The pre-split $440 put O:AAPL150117P00440000 has a non-clean ÷7 strike ($62.857), so
    # OCC re-struck it under the AAPL7 root. AAPL also split 4:1 on 2020-08-31, and the
    # pipeline back-adjusts for ALL known splits (yfinance Adj Close convention), so this
    # 2014 contract lands in ÷28 currency: strike $440/28 ≈ $15.71 → O:AAPL7150117P00015715,
    # premium $1.62/28 ≈ $0.058. The raw symbol is rewritten away entirely (no post-split
    # reuse in a 2014-only window). Continuity across the in-window 2014 split is ~1 (raw
    # would be ~28). Exercises the suffixed-root unification path AND the multi-split
    # back-adjustment of suffixed-root contracts (the fix for the pre-split-leak bug).
    calls, puts, ref = quiet_get_options(options_prices, "AAPL", "2014-06-06", "2014-06-10")
    _describe_options(calls, puts, "AAPL")

    assert "O:AAPL150117P00440000" not in _tickers(puts), "raw pre-split symbol not rewritten"
    succ = "O:AAPL7150117P00015715"
    assert succ in _tickers(puts), f"{succ} (÷28 suffixed-root successor) missing from output"
    pre = _contract_close_at(puts, succ, "2014-06-06")
    post = _contract_close_at(puts, succ, "2014-06-09")
    ratio = pre / post
    print(f"🪚  AAPL {succ}: pre=${pre:.4f}, post=${post:.4f}, ratio={ratio:.4f} (raw ~28)")
    assert 0.5 < ratio < 2.0, f"split-adjusted put continuity ratio {ratio:.3f} (expected ~1)"

    assert quiet_check_options(calls, puts, "AAPL", ref)


@pytest.mark.integration
def test_tsla_2022_split(options_prices: Prices) -> None:
    # TSLA 3:1 split ex-date 2022-08-25 — a clean-strike integer ratio distinct from NVDA's
    # 10:1, on a different (very liquid) underlying. The window predates only this split
    # (TSLA's 2020 5:1 is before it, so fetch_splits returns just the 3:1). The busiest call
    # spanning the boundary should be continuous (ratio ~1, not ~3) after ÷3 back-adjustment,
    # and the structural gate should pass over the whole window.
    calls, puts, ref = quiet_get_options(options_prices, "TSLA", "2022-08-22", "2022-08-26")
    _describe_options(calls, puts, "TSLA")
    assert not calls.empty and not puts.empty, "expected both TSLA calls and puts in range"

    succ = _busiest_spanning_call(calls, "2022-08-24", "2022-08-25")
    assert succ is not None, "no call spans the TSLA split boundary"
    pre = _contract_close_at(calls, succ, "2022-08-24")
    post = _contract_close_at(calls, succ, "2022-08-25")
    ratio = pre / post
    print(f"🪚  TSLA {succ}: pre=${pre:.4f}, post=${post:.4f}, ratio={ratio:.4f} (raw ~3)")
    assert 0.5 < ratio < 2.0, f"split-adjusted call continuity ratio {ratio:.3f} (expected ~1)"

    assert quiet_check_options(calls, puts, "TSLA", ref)


@pytest.mark.integration
def test_aapl_2023_no_split(options_prices: Prices) -> None:
    # A no-split window (AAPL's last split was 2020-08-31), so adjust_options_splits is a
    # no-op and the pipeline exercises the common path: load → backfill → structural gate
    # with zero symbol unification. Complements the two split-spanning tests, which never
    # exercise the clean-window branch. Both sides should be non-empty and pass the gate.
    calls, puts, ref = quiet_get_options(options_prices, "AAPL", "2023-06-01", "2023-06-09")
    _describe_options(calls, puts, "AAPL")
    assert not calls.empty and not puts.empty, "expected both AAPL calls and puts in range"

    assert quiet_check_options(calls, puts, "AAPL", ref)
