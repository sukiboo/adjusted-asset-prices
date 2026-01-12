from src import Prices, check_prices, load_prices, save_prices

if __name__ == "__main__":
    prices = Prices(data_dir="./data/files", debug=True)
    df = prices.get_prices(ticker="BTC-USD", date_start="2025-01-01", date_end=None)
    if check_prices(df):
        print("\n🎉 All checks passed, saving the price data...")
        save_prices(df, save_dir="./data/prices", format="parquet")
    else:
        print("\n❌ Some checks failed, not saving the price data!")

    df = load_prices("BTC-USD.parquet", load_dir="./data/prices")
    print(df)
