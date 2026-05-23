from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from src import Prices
from src.schemas import AssetType
from tests.conftest import describe, quiet_check, quiet_get, require_asset_data


@pytest.fixture(scope="module")
def stocks_prices(data_dir: Path) -> Prices:
    require_asset_data(data_dir, AssetType.STOCKS)
    return Prices(data_dir=str(data_dir))


def _close_at(df: pd.DataFrame, et_date: str) -> float:
    ticker = df.columns[0]
    et_index = df.index.tz_convert("America/New_York")  # type: ignore[attr-defined]
    target = pd.Timestamp(et_date).date()
    mask = (et_index.date == target) & (et_index.hour == 15) & (et_index.minute == 59)
    bars = cast(pd.Series, df.loc[mask, ticker])
    assert len(bars) == 1, f"expected one 15:59 ET bar on {et_date}, got {len(bars)}"
    return float(bars.iloc[0])


@pytest.mark.integration
def test_aapl_2014_split_applied(stocks_prices: Prices) -> None:
    # AAPL 7:1 split ex-date 2014-06-09. Last pre-split session is 2014-06-06.
    # After back-adjustment, the close-to-close ratio across the boundary should
    # be near 1 (daily noise), not near 7 (the raw, unadjusted ratio).
    df, asset_type = quiet_get(stocks_prices, "AAPL", "2014-05-01", "2014-07-31")
    assert asset_type == AssetType.STOCKS
    describe(df, "AAPL")

    pre = _close_at(df, "2014-06-06")
    post = _close_at(df, "2014-06-09")
    ratio = pre / post
    print(
        f"🪚  AAPL split 2014-06-09: pre=${pre:.4f}, post=${post:.4f}, ratio={ratio:.4f} (raw ~7.0)"
    )
    assert 0.95 < ratio < 1.05, f"split-adjusted close ratio {ratio:.3f} (expected ~1)"

    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_spy_long_running(stocks_prices: Prices) -> None:
    # SPY across 2020-2023: quarterly dividends compound (~16 events), several half-days,
    # COVID-era volatility. No splits, so this isolates the dividend-adjustment path
    # over a multi-year range; check_prices must still match yfinance's Adj Close.
    df, asset_type = quiet_get(stocks_prices, "SPY", "2020-01-01", "2023-12-31")
    assert asset_type == AssetType.STOCKS
    describe(df, "SPY")
    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_nvda_two_splits_with_dividends(stocks_prices: Prices) -> None:
    # NVDA across 2020-2024: two splits (4:1 ex 2021-07-20, 10:1 ex 2024-06-10) interleaved
    # with small quarterly dividends. Exercises adjust_splits applied twice in sequence
    # plus the split-then-dividend ordering. Adjusted pre/post close ratios should be ~1
    # across both split boundaries.
    df, asset_type = quiet_get(stocks_prices, "NVDA", "2020-01-01", "2024-12-31")
    assert asset_type == AssetType.STOCKS
    describe(df, "NVDA")

    for split_date, prev_session, raw_ratio in [
        ("2021-07-20", "2021-07-19", "~4.0"),
        ("2024-06-10", "2024-06-07", "~10.0"),
    ]:
        pre = _close_at(df, prev_session)
        post = _close_at(df, split_date)
        ratio = pre / post
        print(
            f"🪚  NVDA split {split_date}: pre=${pre:.4f}, post=${post:.4f}, "
            f"ratio={ratio:.4f} (raw {raw_ratio})"
        )
        assert 0.95 < ratio < 1.05, f"NVDA split-adjusted ratio at {split_date} = {ratio:.3f}"

    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_ge_2021_reverse_split(stocks_prices: Prices) -> None:
    # GE 1:8 reverse split ex-date 2021-08-02. yfinance reports the ratio as 0.125;
    # adjust_splits divides pre-event prices by that (= multiplies by 8), so the adjusted
    # pre/post close ratio should be ~1 (raw would be ~0.125). Window deliberately stays
    # before GE's 2023 GEHC spinoff, which the pipeline does NOT adjust for.
    df, asset_type = quiet_get(stocks_prices, "GE", "2021-07-01", "2021-09-30")
    assert asset_type == AssetType.STOCKS
    describe(df, "GE")

    pre = _close_at(df, "2021-07-30")
    post = _close_at(df, "2021-08-02")
    ratio = pre / post
    print(
        f"🪚  GE split 2021-08-02: pre=${pre:.4f}, post=${post:.4f}, ratio={ratio:.4f} (raw ~0.125)"
    )
    assert 0.95 < ratio < 1.05, f"GE reverse-split-adjusted ratio = {ratio:.3f}"

    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_qyld_monthly_distributions(stocks_prices: Prices) -> None:
    # QYLD pays monthly distributions (~1%/month), most of which are return-of-capital that
    # yfinance lumps under .dividends. The pipeline treats them the same as ordinary
    # dividends — that's correct because yfinance's Adj Close lumps them the same way, so
    # check_prices against yfinance still passes despite the ROC vs. ordinary classification
    # gap (see CLAUDE.md: .capital_gains is empty across every fund tested).
    df, asset_type = quiet_get(stocks_prices, "QYLD", "2023-01-01", "2023-12-31")
    assert asset_type == AssetType.STOCKS
    describe(df, "QYLD")
    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_msft_2004_special_dividend(stocks_prices: Prices) -> None:
    # MSFT paid a $3.08 special dividend ex-date 2004-11-15 on a ~$30 stock → ~10% drop.
    # Last pre-ex session is Friday 2004-11-12. With the dividend correctly back-applied,
    # adjusted pre/post ratio is ~1.0 ± typical daily noise; without it, the raw drop
    # produces ratio ~1.11. Bounds at ±5% cleanly separate the two regimes — unlike the
    # smaller COST 2024 $15 special (~2% drop) we considered, which sits inside daily-noise
    # width and would not signal a missed adjustment.
    df, asset_type = quiet_get(stocks_prices, "MSFT", "2004-10-01", "2004-12-31")
    assert asset_type == AssetType.STOCKS
    describe(df, "MSFT")

    pre = _close_at(df, "2004-11-12")
    post = _close_at(df, "2004-11-15")
    ratio = pre / post
    print(
        f"🪏  MSFT special-div 2004-11-15: pre=${pre:.4f}, post=${post:.4f}, ratio={ratio:.4f} (raw ~1.11)"
    )
    # Upper bound at 1.0 assumes non-negative ex-date drift (stocks usually don't drop the
    # full dividend intraday). True in general, true for MSFT 2004 specifically (observed
    # 0.98), and cleanly excludes the broken/unadjusted case (~1.11).
    assert 0.95 < ratio < 1.0, f"MSFT special-div adjusted ratio = {ratio:.4f}"

    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_bbby_pre_bankruptcy_diverges_from_yfinance(stocks_prices: Prices) -> None:
    # BBBY (Bed Bath & Beyond) traded through ~2023-04-28 before delisting on bankruptcy.
    # yfinance retains BBBY history but applies post-bankruptcy adjustments (final adj_close
    # drops to ~$0.02), while our pipeline only sees the active-trading prices. As a result,
    # compare_to_yf diverges by ~92% — far above any stock threshold — and check_prices
    # returns False. This test asserts the divergence: if it ever flips to passing, yfinance
    # changed its delisting-handling behaviour and we should revisit. Documents a known gap,
    # not a green-light test.
    df, asset_type = quiet_get(stocks_prices, "BBBY", "2023-01-01", "2023-04-21")
    assert asset_type == AssetType.STOCKS
    describe(df, "BBBY")
    assert not quiet_check(
        df, asset_type
    ), "BBBY/yfinance compare unexpectedly passes -- yfinance delisting handling may have changed"
