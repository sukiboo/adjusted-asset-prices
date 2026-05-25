# [WIP] adjusted-asset-prices

Adjust raw historical prices for splits (and optionally dividends), with an opt-in options pass.

Follow-up to the [`historical-asset-prices`](https://github.com/sukiboo/historical-asset-prices) repo,
which produces the raw input files this tool reads from `./data/files/<asset_type>/`.

## Scope

Built for **multi-year price histories** of assets where long histories are hard to source
elsewhere. Accuracy is calibrated for long horizons; short windows can show small
divergences from yfinance's daily Close, because yfinance's snapshot doesn't precisely
line up with our 1-min UTC bars (an offset of a couple of hours of FX market state for
forex, fractions of a minute for crypto). That noise averages out across many days but
can dominate a 5-day sample on a single high-volatility day — a BoJ intervention, a
tariff-day spike, an exchange collapse. If you need a week of data, other providers serve
it more easily; the value here is in multi-year histories you can't get cleanly elsewhere.

## Setup

```bash
pyenv virtualenv 3.12 adjusted-asset-prices
pyenv activate adjusted-asset-prices
pip install -r requirements.txt
```

The repo's `.python-version` pins the venv, so `cd`-ing in auto-activates it if you have
`pyenv virtualenv-init` in your shell.

## Usage

```bash
python main.py <TICKER> [OPTIONS]
```

End-to-end pipeline for one ticker: load raw bars → backfill missing minutes → adjust for
splits (and optionally cash dividends; stocks only, using yfinance metadata) → run sanity
checks → save to `./data/prices/<TICKER>.<format>` → reload and verify the round-trip.

Options:

| flag            | default          | description                                          |
|-----------------|------------------|------------------------------------------------------|
| `--format`      | `parquet`        | output format: `parquet` or `csv`                    |
| `--date-start`  | (earliest)       | inclusive start date, `YYYY-MM-DD`                   |
| `--date-end`    | (latest)         | inclusive end date, `YYYY-MM-DD`                     |
| `--data-dir`    | `./data/files`   | raw input directory                                  |
| `--save-dir`    | `./data/prices`  | adjusted output directory                            |
| `--dividends`   | off              | also back-adjust stocks for cash dividends           |
| `--options`     | off              | also fetch the underlying's option contracts         |

`--dividends` and `--options` are mutually exclusive: the default output is the actual
split-adjusted (not dividend-adjusted) price, so options align with their underlying.

Examples:

```bash
python main.py BTC-USD
python main.py SPY --dividends --format csv --date-start 2024-01-01
python main.py AAPL --options
```

## Caveats

- **Splits and dividends are sourced from yfinance.** The pipeline trusts
  `yf.Ticker(...).splits`, `.dividends`, and `.history()` for the event list and the
  reference closes used in factor computation. Future events known to yfinance at run
  time are applied universally to historical prices (matching yfinance's `Adj Close`
  convention), so a saved file is a snapshot — re-run if new distributions are announced
  after the fact. Stock splits are applied to options too, at the contract level (OCC-style;
  see below), but options are never dividend-adjusted. Non-stock asset types (crypto, forex)
  are passed through as-is — no splits or dividends.
- **Options are an opt-in companion pass** (`--options`), not a standalone ticker mode: you
  pass an underlying and the pipeline runs its stocks pass first, then loads every OSI
  contract on that underlying, OCC-adjusts them for splits (premium ÷ ratio *and* OSI symbol
  rewrite, including numeric-suffix roots like `AAPL7`), RTH-backfills (`[09:30, 15:59]` ET
  via the NYSE calendar), validates, and saves. yfinance has no historical per-contract
  series, so the quality gate is a structural no-arb check (price > 0, calls ≤ underlying,
  puts ≤ strike, intrinsic floors, no bars past expiry) against the split-only underlying —
  which is why `--options` and `--dividends` are mutually exclusive: the gate needs the
  underlying as it actually traded, and dividends are priced into the premium rather than
  back-adjusted out. Spinoff-style corporate actions (where the OCC changes the deliverable,
  not the strike) are skipped. Index/ETF options with an extended 16:15 ET close (SPX, SPXW,
  SPY, QQQ, IWM, ...) have their 16:00–16:14 ET bars dropped on reindex by design —
  `[09:30, 15:59]` is correct for vanilla equity contracts and trades that cleanness for
  partial data on the extended-close products.
- **Stocks** include extended-hours bars (`[04:00, 19:59]` ET via NYSE pre/post session
  bounds), matching Polygon's emission exactly.
- **Hard forks are not adjusted for.** When a chain splits (e.g. BCH from BTC, ETC from
  ETH), pre-fork prices of the surviving ticker are technically inflated by the value of
  the spun-off coin, analogously to a stock split. The pipeline does not currently
  account for this — pre-fork bars are passed through as-is. Irrelevant for most majors
  in typical date ranges, but worth knowing if you backtest across a known fork date.
- **Backfilled minutes are synthetic and unmarked.** Missing 1-minute bars are filled
  by log-space linear interpolation between the surrounding real prints; the output
  carries no flag indicating which rows were interpolated vs. observed. For liquid
  majors this is rare and the interpolation is close to truth, but for thin-volume
  assets with long gaps the synthetic values can drift meaningfully from what real
  trades would have produced.

## Testing

End-to-end integration tests in `tests/integration/` run the full pipeline against real
Polygon flat files and live yfinance data — no mocks. Run with:

```bash
pytest -m integration -v -s
```

`-s` disables stdout capture so each test's scenario header, bar counts, price range, and
boundary spot-checks print to the terminal as it runs. Drop `-s` if you want a quieter pass.

Tests skip per-asset when `data/files/<asset>/` is empty, so wire up the data the same way
you would for `main.py` (a symlink to your raw-file mirror works). Current coverage:

- **Stocks**: AAPL 7:1 split (split-only path), AAPL 2023 split-only-vs-dividend-adjusted
  both-ways (convention switch), NVDA 4:1 + 10:1 splits with dividends, GE 1:8 reverse split,
  SPY 2020–2023 dividends multi-year, QYLD monthly ROC distributions, MSFT 2004 $3.08 special
  dividend (~10% drop), BBBY pre-bankruptcy window.
- **Crypto**: BTC-USD Luna/Terra crash (crypto-threshold stress), BTC-USD 2020–2022 multi-year,
  ETH-USD 2021–2022 (Merge + FTX), SOL-USD 2022–2023 (FTX collapse + recovery).
- **Forex**: EUR-USD weekend-crossing week, EUR-USD 2022–2024 multi-year.
- **Options**: NVDA 10:1 2024 (clean-strike unification), AAPL 7:1 2014 (non-clean /
  suffixed-root unification), TSLA 3:1 2022 (clean integer ratio), AAPL 2023 no-split
  (clean-window structural gate). Validated via the structural no-arb gate (`check_options`)
  against the split-only underlying, since yfinance has no historical per-contract series.

Expect roughly 2–5 minutes per long-running test on first run.
