import os
import requests
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import logging
from typing import Tuple, List, Dict
import time

# Create data folder if it doesn't exist.
data_dir = "data"
os.makedirs(data_dir, exist_ok=True)

# Configure logging: output to file only.
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create file handler for logging.
fh = logging.FileHandler('nse_data.log', mode='a')
fh.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

# Disable propagation so logs are not printed to terminal.
logger.propagate = False


class NSEDataFetcher:
    """
    Fetches live NIFTY 50 data from the specified URL.
    This implementation initializes the session by accessing the
    specified URL and uses additional headers (including Referer and Origin)
    to simulate a genuine browser request.
    """
    def __init__(self, api_url: str = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"):
        self.api_url = api_url
        self.session = requests.Session()
        self.headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/112.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/market-data/live-equity-market?symbol=NIFTY%2050",
            "Origin": "https://www.nseindia.com",
            "sec-ch-ua": '"Chromium";v="112", "Google Chrome";v="112", "Not:A-Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
        try:
            logging.info("Initializing session by accessing specified URL...")
            # Prime the session by accessing the specified URL.
            self.session.get("https://www.nseindia.com/market-data/live-equity-market?symbol=NIFTY%2050",
                             headers=self.headers, timeout=10)
        except Exception as e:
            logging.error("Error initiating session: %s", e)
            raise

    def fetch_live_data(self) -> pd.DataFrame:
        """
        Fetch live data using the API endpoint.
        Returns:
            pd.DataFrame: Live data as a DataFrame.
        Raises:
            Exception: if the request or JSON parsing fails.
        """
        try:
            logging.info("Requesting live data from NSE API...")
            response = self.session.get(self.api_url, headers=self.headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            if "data" not in data:
                raise Exception("Expected key 'data' not found in JSON response.")
            df = pd.DataFrame(data["data"])
            logging.info("Live data fetched successfully with %d records.", len(df))
            return df
        except Exception as e:
            logging.error("Error fetching live data: %s", e)
            raise

    def get_nifty50_symbols(self) -> List[str]:
        """
        Extracts the list of stock symbols from the live data.
        Returns:
            List[str]: Stock symbols appended with ".NS" for yfinance.
        """
        try:
            df = self.fetch_live_data()
            if "symbol" not in df.columns:
                raise Exception("Expected 'symbol' column not found in data.")
            symbols = df["symbol"].tolist()
            symbols = [sym + ".NS" for sym in symbols]
            logging.info("Extracted %d symbols.", len(symbols))
            return symbols
        except Exception as e:
            logging.error("Error extracting symbols: %s", e)
            raise


class NSEDataAnalyzer:
    """
    Analyzes NSE data using live data and historical data from yfinance.
    """
    def __init__(self, symbols: List[str]):
        self.symbols = symbols

    def fetch_yfinance_data(self, period: str = "1y") -> Dict[str, pd.DataFrame]:
        """
        Fetches historical data for all symbols using yfinance.
        """
        data: Dict[str, pd.DataFrame] = {}
        for sym in self.symbols:
            try:
                logging.info("Fetching historical data for %s...", sym)
                ticker = yf.Ticker(sym)
                hist = ticker.history(period=period)
                if hist.empty:
                    logging.warning("No historical data for %s", sym)
                else:
                    data[sym] = hist
            except Exception as e:
                logging.error("Error fetching data for %s: %s", sym, e)
        return data

    def get_top_gainers_losers(self, live_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Identifies the top 5 gainers and losers of the day based on the percentage change.
        NOTE: Instead of '%change', we use 'pChange' as per the table header.
        """
        try:
            live_df["pChange"] = live_df["pChange"].astype(str).str.replace('%', '').astype(float)
            gainers = live_df.sort_values("pChange", ascending=False).head(5)
            losers = live_df.sort_values("pChange", ascending=True).head(5)
            logging.info("Identified top gainers and losers.")
            return gainers, losers
        except Exception as e:
            logging.error("Error computing top gainers/losers: %s", e)
            raise

    def get_52week_analysis(self, hist_data: Dict[str, pd.DataFrame]) -> Tuple[List[Tuple[str, float, float]], List[Tuple[str, float, float]]]:
        """
        Identifies 5 stocks trading at least 30% below their 52-week high and
        5 stocks trading at least 20% above their 52-week low.
        """
        below_high: List[Tuple[str, float, float]] = []
        above_low: List[Tuple[str, float, float]] = []
        for sym, df in hist_data.items():
            try:
                if df.empty:
                    continue
                current_price = df["Close"].iloc[-1]
                high_52w = df["Close"].max()
                low_52w = df["Close"].min()
                if current_price <= 0.70 * high_52w:
                    below_high.append((sym, current_price, high_52w))
                if current_price >= 1.20 * low_52w:
                    above_low.append((sym, current_price, low_52w))
            except Exception as e:
                logging.error("Error in 52-week analysis for %s: %s", sym, e)
                continue
        below_high = sorted(below_high, key=lambda x: x[1] / x[2])[:5]
        above_low = sorted(above_low, key=lambda x: -(x[1] / x[2]))[:5]
        return below_high, above_low

    def get_30day_returns(self, hist_data: Dict[str, pd.DataFrame]) -> List[Tuple[str, float]]:
        """
        Calculates the highest 30-day returns for each symbol.
        """
        returns: List[Tuple[str, float]] = []
        for sym, df in hist_data.items():
            try:
                if df.shape[0] < 30:
                    continue
                current_price = df["Close"].iloc[-1]
                price_30d_ago = df["Close"].iloc[-30]
                ret = ((current_price - price_30d_ago) / price_30d_ago) * 100
                returns.append((sym, ret))
            except Exception as e:
                logging.error("Error computing 30-day return for %s: %s", sym, e)
                continue
        returns = sorted(returns, key=lambda x: x[1], reverse=True)
        return returns

    def plot_gainers_losers(self, gainers: pd.DataFrame, losers: pd.DataFrame) -> None:
        """
        Plots bar charts for the top 5 gainers and losers.
        Saves the plot as an image file in the data folder and then closes the plot automatically.
        """
        try:
            fig, ax = plt.subplots(1, 2, figsize=(15, 6))
            ax[0].bar(gainers["symbol"], gainers["pChange"].astype(float), color='green')
            ax[0].set_title("Top 5 Gainers")
            ax[0].set_xlabel("Symbol")
            ax[0].set_ylabel("% Change")
            ax[0].tick_params(axis='x', rotation=45)
            
            ax[1].bar(losers["symbol"], losers["pChange"].astype(float), color='red')
            ax[1].set_title("Top 5 Losers")
            ax[1].set_xlabel("Symbol")
            ax[1].set_ylabel("% Change")
            ax[1].tick_params(axis='x', rotation=45)
            
            plt.tight_layout()
            plot_path = os.path.join(data_dir, "gainers_losers.png")
            plt.savefig(plot_path)
            plt.close('all')
            logging.info("Bar charts saved to %s and closed automatically.", plot_path)
        except Exception as e:
            logging.error("Error plotting bar charts: %s", e)
            raise


def main():
    output_lines = []
    try:
        # Initialize the data fetcher using the specified URL.
        fetcher = NSEDataFetcher()
        live_df = fetcher.fetch_live_data()
        
        # Extract stock symbols (appending '.NS' for yfinance).
        nifty50_symbols = fetcher.get_nifty50_symbols()
        
        # Instantiate the data analyzer.
        analyzer = NSEDataAnalyzer(nifty50_symbols)
        
        # Compute top gainers and losers.
        gainers, losers = analyzer.get_top_gainers_losers(live_df)
        output_lines.append("----- Top 5 Gainers -----")
        for idx, row in gainers.iterrows():
            line = f"Symbol: {row['symbol']}, % Change: {row['pChange']:.2f}%"
            # print(line)
            output_lines.append(line)
        output_lines.append("-------------------------\n")
        
        output_lines.append("----- Top 5 Losers -----")
        for idx, row in losers.iterrows():
            line = f"Symbol: {row['symbol']}, % Change: {row['pChange']:.2f}%"
            # print(line)
            output_lines.append(line)
        output_lines.append("-------------------------\n")
        
        # Fetch historical data (using 1 year).
        hist_data = analyzer.fetch_yfinance_data(period="1y")
        
        # 52-week analysis.
        below_high, above_low = analyzer.get_52week_analysis(hist_data)
        output_lines.append("----- Stocks 30% Below 52-Week High -----")
        for sym, current, high in below_high:
            line = f"Symbol: {sym}, Current Price: {current:.2f}, 52-Week High: {high:.2f}"
            # print(line)
            output_lines.append(line)
        output_lines.append("-----------------------------------------\n")
        
        output_lines.append("----- Stocks 20% Above 52-Week Low -----")
        for sym, current, low in above_low:
            line = f"Symbol: {sym}, Current Price: {current:.2f}, 52-Week Low: {low:.2f}"
            # print(line)
            output_lines.append(line)
        output_lines.append("----------------------------------------\n")
        
        # 30-day returns.
        returns_30d = analyzer.get_30day_returns(hist_data)
        output_lines.append("----- Top 5 Stocks by 30-Day Return -----")
        for sym, ret in returns_30d[:5]:
            line = f"Symbol: {sym}, 30-Day Return: {ret:.2f}%"
            # print(line)
            output_lines.append(line)
        output_lines.append("-----------------------------------------\n")
        
        # Save the output text to a file.
        results_path = os.path.join(data_dir, "results.txt")
        with open(results_path, "w") as f:
            f.write("\n".join(output_lines))
        logging.info("Text output saved to %s", results_path)
        
        # Plot and save the gainers and losers.
        analyzer.plot_gainers_losers(gainers, losers)
        
        # Optionally, re-read the saved file and print its content
        print("\n----- Results from results.txt -----")
        with open(results_path, "r") as f:
            file_content = f.read()
            print(file_content)
        print("--------------------------------------")
        
    except Exception as e:
        logging.error("An error occurred in main execution: %s", e)


if __name__ == "__main__":
    main()
