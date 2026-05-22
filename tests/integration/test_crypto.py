from pathlib import Path

import pytest

from src import Prices
from src.schemas import AssetType
from tests.conftest import describe, quiet_check, quiet_get, require_asset_data


@pytest.fixture(scope="module")
def crypto_prices(data_dir: Path) -> Prices:
    require_asset_data(data_dir, AssetType.CRYPTO)
    return Prices(data_dir=str(data_dir))


@pytest.mark.integration
def test_btc_luna_crash_window(crypto_prices: Prices) -> None:
    # BTC-USD over the May-Jun 2022 Luna/Terra collapse: a high-volatility window that
    # stresses the check gate against yfinance's intrinsic noise floor. yfinance's daily
    # Close for crypto is not drawn from its own 1-min feed (empirically ~0.02-0.07% off
    # from any 1-min bar even on a quiet week), so p99 |diff| can spike on fast days
    # without anything being wrong on our end. The soft-AND gate (fail only if BOTH p50
    # AND p99 exceed thresholds) absorbs that; tightening to OR would false-positive here.
    df, asset_type = quiet_get(crypto_prices, "BTC-USD", "2022-05-01", "2022-06-30")
    assert asset_type == AssetType.CRYPTO
    describe(df, "BTC-USD")
    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_btc_long_running(crypto_prices: Prices) -> None:
    # BTC-USD across 2020-2022: ~1.5M-bar continuous 1-min grid spanning the COVID
    # crash, bull run, and Luna/FTX selloff. Exercises backfill + comparison at scale
    # and catches regressions that only surface on larger inputs (memory blowups,
    # accumulated tz drift, etc.).
    df, asset_type = quiet_get(crypto_prices, "BTC-USD", "2020-01-01", "2022-12-31")
    assert asset_type == AssetType.CRYPTO
    describe(df, "BTC-USD")
    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_eth_2021_2022(crypto_prices: Prices) -> None:
    # ETH-USD across 2021-2022: covers the 2021 bull run, the Sept-2022 Merge (PoW → PoS,
    # no price discontinuity but a major protocol event), Luna in May, and the Nov 2022
    # FTX collapse. Distinct underlying from BTC so we exercise the comparison path on a
    # second high-liquidity coin where any per-ticker yfinance quirks would surface.
    df, asset_type = quiet_get(crypto_prices, "ETH-USD", "2021-01-01", "2022-12-31")
    assert asset_type == AssetType.CRYPTO
    describe(df, "ETH-USD")
    assert quiet_check(df, asset_type)


@pytest.mark.integration
def test_sol_2022_2023(crypto_prices: Prices) -> None:
    # SOL-USD across 2022-2023: extreme drawdown coverage (~$170 → ~$8 through the FTX
    # collapse in Nov 2022, then a ~15x recovery into late 2023). A lower-liquidity coin
    # than BTC/ETH with sharper boundary noise, so this is the most aggressive test of
    # whether soft-AND absorbs yfinance's daily-vs-minute inconsistency over a long range.
    df, asset_type = quiet_get(crypto_prices, "SOL-USD", "2022-01-01", "2023-12-31")
    assert asset_type == AssetType.CRYPTO
    describe(df, "SOL-USD")
    assert quiet_check(df, asset_type)
