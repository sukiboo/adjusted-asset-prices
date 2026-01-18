from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import pandas as pd
import seaborn as sns
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

sns.set_theme(style="darkgrid", palette="muted", font="monospace", rc={"lines.linewidth": 2})


def compute_centered_rolling_average(
    df: pd.DataFrame, ticker: str, window_minutes: int = 1440
) -> pd.Series:
    """
    Compute a centered rolling average for each timestamp.

    This removes the bias from using calendar-day boundaries by using a symmetric
    window around each point (e.g., ±12 hours for a 24-hour window).

    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame with asset prices indexed by timestamp
    ticker : str
        Column name for the asset price (e.g., 'ETH-USD')
    window_minutes : int
        Size of the rolling window in minutes (default: 1440 = 24 hours)

    Returns:
    --------
    pd.Series
        Centered rolling average prices indexed by timestamp
    """
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # Compute centered rolling mean (center=True makes it symmetric around each point)
    rolling_avg: pd.Series = (
        df[ticker]
        .rolling(  # type: ignore[assignment]
            window=window_minutes, min_periods=window_minutes // 2, center=True
        )
        .mean()
    )

    return rolling_avg


def compute_relative_diffs(
    df: pd.DataFrame, ticker: str, window_minutes: int = 1440
) -> pd.DataFrame:
    """
    Compute relative difference from centered rolling average for each timestamp.

    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame with asset prices indexed by timestamp
    ticker : str
        Column name for the asset price (e.g., 'ETH-USD')
    window_minutes : int
        Size of the rolling window in minutes (default: 1440 = 24 hours)

    Returns:
    --------
    pd.DataFrame
        DataFrame with 'price', 'rolling_avg', 'relative_diff', 'hour', 'minute' columns
    """
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    result: pd.DataFrame = pd.DataFrame(index=df.index)
    result["price"] = df[ticker]
    result["rolling_avg"] = compute_centered_rolling_average(df, ticker, window_minutes)
    result["relative_diff"] = (result["price"] - result["rolling_avg"]) / result["rolling_avg"]

    idx: pd.DatetimeIndex = result.index  # type: ignore[assignment]
    result["hour"] = idx.hour  # type: ignore[attr-defined]
    result["minute"] = idx.minute  # type: ignore[attr-defined]

    # Drop rows where rolling average couldn't be computed (edges)
    result = result.dropna()

    return result


def analyze_time_slot(
    relative_diffs_df: pd.DataFrame,
    hour: int,
    minute: int,
) -> dict[str, Any]:
    """
    Analyze relative differences for a specific time slot.

    Parameters:
    -----------
    relative_diffs_df : pd.DataFrame
        DataFrame with pre-computed relative differences (from compute_relative_diffs)
    hour : int
        Hour of day (0-23)
    minute : int
        Minute of hour (0-59)

    Returns:
    --------
    dict with:
        - relative_diffs: array of relative differences for each day (as decimals, e.g., 0.001 = 0.1%)
        - mean: mean relative difference
        - std: standard deviation of relative differences
        - median: median relative difference
        - p5, p25, p75, p95: percentiles
        - n_observations: number of days with data at this time
    """
    # Filter to the specific hour and minute
    mask: pd.Series = (relative_diffs_df["hour"] == hour) & (relative_diffs_df["minute"] == minute)
    time_data: pd.DataFrame = relative_diffs_df[mask]  # type: ignore[assignment]

    if len(time_data) == 0:
        return {
            "relative_diffs": np.array([]),
            "mean": np.nan,
            "std": np.nan,
            "median": np.nan,
            "p5": np.nan,
            "p25": np.nan,
            "p75": np.nan,
            "p95": np.nan,
            "n_observations": 0,
        }

    relative_diffs: npt.NDArray[np.floating[Any]] = time_data["relative_diff"].values  # type: ignore[assignment]

    return {
        "relative_diffs": relative_diffs,
        "mean": float(np.mean(relative_diffs)),
        "std": float(np.std(relative_diffs)),
        "median": float(np.median(relative_diffs)),
        "p5": float(np.percentile(relative_diffs, 5)),
        "p25": float(np.percentile(relative_diffs, 25)),
        "p75": float(np.percentile(relative_diffs, 75)),
        "p95": float(np.percentile(relative_diffs, 95)),
        "n_observations": len(relative_diffs),
    }


def analyze_time_slots(
    df: pd.DataFrame,
    ticker: str,
    hours: list[int] | None = None,
    minutes: list[int] | None = None,
    window_minutes: int = 1440,
) -> pd.DataFrame:
    """
    Analyze specified time slots throughout the day.

    Uses a centered rolling average to remove intraday drift bias. Each price is
    compared to the average of prices in a symmetric window around it (default ±12 hours),
    rather than an arbitrary calendar-day average.

    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame with asset prices indexed by timestamp
    ticker : str
        Column name for the asset price (e.g., 'ETH-USD')
    hours : list, optional
        List of hours to analyze (default: 0-23)
    minutes : list, optional
        List of minutes to analyze (default: [0])
    window_minutes : int
        Size of the centered rolling window in minutes (default: 1440 = 24 hours)

    Returns:
    --------
    pd.DataFrame
        Results for all time slots, sorted by median relative difference (ascending)
    """
    if hours is None:
        hours = list(range(24))
    if minutes is None:
        minutes = [0]

    # Pre-compute relative differences using centered rolling average
    relative_diffs_df: pd.DataFrame = compute_relative_diffs(df, ticker, window_minutes)

    results: list[dict[str, Any]] = []
    for hour in hours:
        for minute in minutes:
            result: dict[str, Any] = analyze_time_slot(relative_diffs_df, hour, minute)
            result["hour"] = hour
            result["minute"] = minute
            result["time"] = f"{hour:02d}:{minute:02d}"
            results.append(result)

    results_df: pd.DataFrame = pd.DataFrame(results)

    # Sort by median (ascending = lowest/cheapest first)
    results_df = results_df.sort_values("median", ascending=True)

    return results_df


def plot_time_analysis(results_df: pd.DataFrame, ticker: str) -> None:
    """
    Plot the relative price difference for each time slot.

    Parameters:
    -----------
    results_df : pd.DataFrame
        DataFrame with analysis results for all time slots
    ticker : str
        Asset ticker for the title
    """
    fig: Figure
    ax: Axes
    fig, ax = plt.subplots(figsize=(14, 6))

    # Sort by time for plotting
    results_sorted: pd.DataFrame = results_df.sort_values(["hour", "minute"]).copy()
    x_positions: range = range(len(results_sorted))

    # Plot percentile bands
    ax.fill_between(
        x_positions,
        results_sorted["p5"],
        results_sorted["p95"],
        alpha=0.2,
        color="steelblue",
        label="5th-95th percentile",
    )
    ax.fill_between(
        x_positions,
        results_sorted["p25"],
        results_sorted["p75"],
        alpha=0.3,
        color="steelblue",
        label="25th-75th percentile",
    )

    # Plot median
    ax.plot(x_positions, results_sorted["median"], color="steelblue", linewidth=2, label="Median")

    # Zero line
    ax.axhline(y=0, color="gray", linestyle="-", linewidth=1, alpha=0.6)

    ax.set_xlabel("Time of Day")
    ax.set_ylabel("Relative Difference from Daily Average (%)")
    ax.set_title(f"{ticker}: Price at Each Time vs Daily Average")

    # Determine tick spacing based on number of time slots
    n_slots: int = len(results_sorted)
    tick_spacing: int = max(1, n_slots // 24)  # Aim for ~24 ticks
    ax.set_xticks(list(x_positions)[::tick_spacing])
    ax.set_xticklabels(results_sorted["time"].iloc[::tick_spacing], rotation=45, ha="right")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x * 100:+.2f}%"))
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.6)

    plt.tight_layout()
    plt.show()


def print_summary(results_df: pd.DataFrame, ticker: str) -> None:
    """
    Print summary statistics for the analysis.

    Parameters:
    -----------
    results_df : pd.DataFrame
        DataFrame with analysis results for all time slots
    ticker : str
        Asset ticker for the title
    """
    n_obs: int = int(results_df["n_observations"].iloc[0])
    print("=" * 100)
    print(f"{ticker} analysis based on {n_obs} days of data (relative to daily average)")
    print("=" * 100)

    print("\nbest times to buy (price below daily average):")
    print("-" * 100)
    for _, row in results_df.head(10).iterrows():
        print(
            f"  {row['time']}  |  mean: {row['mean']:+.3%}  |  "
            f"median: {row['median']:+.3%}  |  std: {row['std']:.3%}  |  "
            f"[p25={row['p25']:+.3%}, p75={row['p75']:+.3%}]"
        )

    print("\nworst times to buy (price above daily average):")
    print("-" * 100)
    for _, row in results_df.tail(10).iloc[::-1].iterrows():
        print(
            f"  {row['time']}  |  mean: {row['mean']:+.3%}  |  "
            f"median: {row['median']:+.3%}  |  std: {row['std']:.3%}  |  "
            f"[p25={row['p25']:+.3%}, p75={row['p75']:+.3%}]"
        )


if __name__ == "__main__":
    DATA_DIR: str = "./data/prices"
    ticker: str = "SOL-USD"

    df: pd.DataFrame = pd.read_parquet(f"{DATA_DIR}/{ticker}.parquet")
    df = df[df.index >= pd.Timestamp("2020-01-01", tz="UTC")]  # type: ignore[assignment]

    hours: list[int] = list(range(24))
    minutes: list[int] = list(range(60))
    results_df: pd.DataFrame = analyze_time_slots(df, ticker, hours, minutes)

    print_summary(results_df, ticker)
    plot_time_analysis(results_df, ticker)
