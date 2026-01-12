from src import Prices, check_prices, load_prices, save_prices
from src.schemas import ChecksConfig

checks_config: ChecksConfig = {
    "gap_threshold_mins": 1,
    "num_gaps_display": 10,
    "diff_threshold_avg": 0.1,
    "diff_threshold_max": 5.0,
    "show_plot": True,
}


if __name__ == "__main__":
    ticker = "BTC-USD"
    format = "parquet"
    date_start = None
    date_end = None

    prices = Prices(data_dir="./data/files", debug=True)
    df = prices.get_prices(ticker=ticker, date_start=date_start, date_end=date_end)
    if check_prices(df, config=checks_config):
        print("\n🎉 All checks passed, saving the price data...")
        save_prices(df, save_dir="./data/prices", format=format)
    else:
        print("\n❌ Some checks failed, not saving the price data!")

    df = load_prices(f"{ticker}.{format}", load_dir="./data/prices")
    print(df)
