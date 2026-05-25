from typing import cast

import numpy as np
import pandas as pd

from ..schemas import OptionsChecksConfig, PriceFileFormat
from ..utils import parse_osi_ticker, save_options, verify_saved_options


def check_options(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    underlying: str,
    underlying_df: pd.DataFrame,
    config: OptionsChecksConfig,
) -> bool:
    """Structural gate: four no-arb self-consistency checks against the underlying
    (yfinance has no historical per-contract series to compare to):
      1. positivity (P > 0, C > 0) — strict, every bar
      2. no bars past expiry — strict, every bar
      3. upper bounds (P ≤ K, C ≤ S) — relative-p99-gated, deep-ITM bars excluded
      4. intrinsic floors (P ≥ K - S, C ≥ S - K) — same gating
    `underlying_df` must be SPLIT-ONLY (not dividend-adjusted): dividends are priced into
    the premium ahead of ex-date, so a dividend-adjusted series overstates intrinsic.
    """
    print(f"\n🔍 Checking {underlying} options...")
    if calls.empty and puts.empty:
        print("⚠️  Both calls and puts empty; nothing to check")
        return False

    threshold_rel = config["noarb_violation_p99_rel"]
    deep_itm_cap = config["deep_itm_moneyness_cap"]
    if underlying not in underlying_df.columns:
        raise KeyError(
            f"underlying_df must have a column named `{underlying}`; got {list(underlying_df.columns)}"
        )
    underlying_series = underlying_df[underlying]

    results: list[bool] = []
    for side, df in [("calls", calls), ("puts", puts)]:
        if df.empty:
            print(f"⚠️  {side} side empty; skipping {side} checks")
            continue
        results.extend(_run_side_checks(side, df, underlying_series, threshold_rel, deep_itm_cap))
    return all(results) if results else False


def _run_side_checks(
    side: str,
    df: pd.DataFrame,
    underlying_series: pd.Series,
    threshold_rel: float,
    deep_itm_cap: float,
) -> list[bool]:
    """Run the four checks on one side (calls or puts). Strikes, the underlying snapshot,
    intrinsic value, and the deep-ITM mask are computed once and shared across checks."""
    ts_level = cast(pd.DatetimeIndex, df.index.get_level_values("timestamp_utc"))
    ticker_level = df.index.get_level_values("ticker")
    parsed_by_ticker = {t: parse_osi_ticker(cast(str, t)) for t in ticker_level.unique()}
    strikes = np.array([parsed_by_ticker[t].strike for t in ticker_level])
    underlying_at_t = cast(pd.Series, underlying_series.reindex(ts_level)).to_numpy()
    close = df["close"].to_numpy()

    # Intrinsic and the shallow (= not-deep-ITM) mask are shared by both no-arb bound
    # checks. Deep-ITM bars (intrinsic > cap × underlying) are dropped from those checks
    # only — positivity and expiry still cover every bar.
    if side == "calls":
        intrinsic = np.maximum(underlying_at_t - strikes, 0.0)
    else:
        intrinsic = np.maximum(strikes - underlying_at_t, 0.0)
    shallow = intrinsic <= deep_itm_cap * underlying_at_t

    return [
        _check_positive(side, close, ts_level, ticker_level),
        _check_no_bars_past_expiry(side, ts_level, ticker_level, parsed_by_ticker),
        _check_upper_bound(side, close, strikes, underlying_at_t, shallow, threshold_rel),
        _check_intrinsic_floor(side, close, intrinsic, underlying_at_t, shallow, threshold_rel),
    ]


def _format_examples(
    ts: pd.DatetimeIndex, tickers: pd.Index, mask: np.ndarray, values: np.ndarray, n: int = 3
) -> str:
    idx = np.flatnonzero(mask)[:n]
    parts = [f"{tickers[i]} @ {ts[i]} = {values[i]:.4f}" for i in idx]
    return "; ".join(parts)


def _check_positive(side: str, close: np.ndarray, ts: pd.DatetimeIndex, tickers: pd.Index) -> bool:
    bad = ~(close > 0)
    n_bad = int(bad.sum())
    if n_bad:
        print(
            f"❗ {side}: {n_bad:,} bars are not strictly positive "
            f"(worst: {_format_examples(ts, tickers, bad, close)})"
        )
        return False
    print(f"✔️  {side} > 0: all {len(close):,} bars positive")
    return True


def _check_no_bars_past_expiry(
    side: str, ts: pd.DatetimeIndex, tickers: pd.Index, parsed_by_ticker: dict
) -> bool:
    bar_dates = np.asarray(ts.tz_convert("America/New_York").date)
    expiries = np.asarray([parsed_by_ticker[t].expiry for t in tickers])
    bad = bar_dates > expiries
    n_bad = int(bad.sum())
    if n_bad:
        # Inline rather than reuse _format_examples — values here are dates, not
        # floats, and `:.4f` on a date silently renders the literal `.4f` (strftime
        # treats it as a template with no directives).
        idx = np.flatnonzero(bad)[:3]
        ex = "; ".join(
            f"{tickers[i]} @ {ts[i]} (bar date {bar_dates[i]} > expiry {expiries[i]})" for i in idx
        )
        print(f"❗ {side}: {n_bad:,} bars past contract expiry (worst: {ex})")
        return False
    print(f"✔️  {side} bars all within contract expiry")
    return True


def _check_upper_bound(
    side: str,
    close: np.ndarray,
    strikes: np.ndarray,
    underlying_at_t: np.ndarray,
    shallow: np.ndarray,
    threshold_rel: float,
) -> bool:
    """Calls: close ≤ underlying. Puts: close ≤ strike. A last print lagging spot can
    breach by a few % without an arb; systematic mis-scaling pushes p99 past the band.
    """
    label = "underlying" if side == "calls" else "strike"
    upper = underlying_at_t if side == "calls" else strikes
    rel_breach = np.maximum(close - upper, 0.0) / underlying_at_t
    return _gate_relative_violation(
        side, f"≤ {label}", "rel breach", rel_breach, shallow, threshold_rel
    )


def _check_intrinsic_floor(
    side: str,
    close: np.ndarray,
    intrinsic: np.ndarray,
    underlying_at_t: np.ndarray,
    shallow: np.ndarray,
    threshold_rel: float,
) -> bool:
    """Calls: close ≥ max(S - K, 0). Puts: close ≥ max(K - S, 0). Stale ITM prints sit a
    few % below intrinsic without an arb; a missed split shows up as a far larger shortfall
    that also hits near-the-money contracts, so it survives the deep-ITM exclusion.
    """
    rel_shortfall = np.maximum(intrinsic - close, 0.0) / underlying_at_t
    return _gate_relative_violation(
        side, "intrinsic floor", "rel shortfall", rel_shortfall, shallow, threshold_rel
    )


def _gate_relative_violation(
    side: str,
    desc: str,
    metric: str,
    rel_violation: np.ndarray,
    shallow: np.ndarray,
    threshold_rel: float,
) -> bool:
    """Percentile-gate a relative no-arb violation over non-deep-ITM (`shallow`) bars.
    `rel_violation` is the per-bar breach/shortfall already divided by the underlying;
    the gate fires when its p99 over the shallow bars exceeds `threshold_rel`.
    """
    n_excl = int((~shallow).sum())
    if not shallow.any():
        print(f"✔️  {side} {desc}: no near-the-money bars to check ({n_excl:,} deep-ITM excluded)")
        return True
    rel = rel_violation[shallow]
    p50 = float(np.percentile(rel, 50))
    p99 = float(np.percentile(rel, 99))
    worst = float(rel.max())
    n_viol = int((rel > 0).sum())
    status = "❗" if p99 > threshold_rel else "✔️ "
    print(
        f"{status} {side} {desc}: {metric} p50/p99/max = "
        f"{p50:.2%}/{p99:.2%}/{worst:.2%} over {n_viol:,} violating bars "
        f"(excl {n_excl:,} deep-ITM; p99 threshold {threshold_rel:.2%})"
    )
    return p99 <= threshold_rel


def save_options_if_valid(
    calls: pd.DataFrame,
    puts: pd.DataFrame,
    underlying: str,
    underlying_df: pd.DataFrame,
    save_dir: str,
    format: PriceFileFormat,
    config: OptionsChecksConfig,
) -> bool:
    """Run the structural gate; on pass, save both sides and verify the round-trip."""
    if not check_options(calls, puts, underlying, underlying_df, config):
        print(f"\n❌ {underlying} options checks failed, not saving!")
        return False
    print(f"\n🎉 {underlying} options checks passed, saving...")
    save_options(calls, puts, underlying, save_dir=save_dir, format=format)
    return verify_saved_options(calls, puts, underlying, save_dir=save_dir, format=format)
