from src import Prices, check_prices

if __name__ == "__main__":
    prices = Prices(data_dir="./data/files", debug=True)
    df = prices.get_prices(ticker="BTC-USD", date_start="2025-01-01", date_end=None)
    check_prices(df)
