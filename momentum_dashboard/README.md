# Momentum Strategy Dashboard

A self-contained Streamlit dashboard for visualizing and analyzing momentum-based investment strategies.

## 📁 Folder Structure

```
momentum_dashboard/
├── momentum_app.py          # Main Streamlit application
├── td_client.py             # TrueData API client module
├── Ticker_Master.xlsx       # Stock universe data (Nifty 500)
├── .streamlit/              # Streamlit configuration
│   └── config.toml          # App configuration settings
├── cache/                   # Auto-generated cache folder
│   ├── daily_nav.parquet
│   ├── daily_returns.parquet
│   ├── stock_level_df.parquet
│   ├── nav_df.parquet
│   ├── stock_stats.parquet
│   └── metadata.parquet
└── README.md                # This file
```

> [!IMPORTANT]
> **When copying this folder to another system:**
> 1. **Include the `cache/` folder** with all its parquet files
> 2. This ensures identical results on the new system
> 3. Without cache, you'll need to re-fetch data (5-10 minutes)
> 4. Cache size is small (~10-20 MB compressed)

## 📦 Moving to Another System

To get the same results on a different computer:

**Option 1: Copy Everything (Recommended)**
```powershell
# Copy entire folder including cache
Copy-Item -Path "momentum_dashboard" -Destination "D:\NewLocation\" -Recurse -Force
```

**Option 2: Fresh Data on New System**
```powershell
# Copy folder, then delete cache on new system
Remove-Item "D:\NewLocation\momentum_dashboard\cache\*.parquet"
# Run app and click "Refresh Data"
```

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- pip (Python package manager)

### Installation

1. **Install required packages:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Navigate to the dashboard folder:**
   ```bash
   cd "C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\momentum_dashboard"
   ```

3. **Run the application:**
   ```bash
   streamlit run momentum_app.py
   ```

The dashboard will automatically open in your default web browser at `http://localhost:8501`

## ☁️ Deploy to Streamlit Cloud

### Quick Deploy

1. **Push to GitHub** (if not already done):
   ```bash
   git add .
   git commit -m "Configure for Streamlit Cloud deployment"
   git push origin main
   ```

2. **Deploy on Streamlit Cloud**:
   - Visit [share.streamlit.io](https://share.streamlit.io)
   - Sign in with GitHub
   - Click "New app"
   - Select repository: `quant-arch/Momentum`
   - Set main file path: `momentum_dashboard/momentum_app.py`
   - Click "Deploy"

3. **Configure Secrets** (Required):
   - Go to your app settings → Secrets
   - Add TrueData credentials:
   ```toml
   [truedata]
   username = "YOUR_TRUEDATA_USERNAME"
   password = "YOUR_TRUEDATA_PASSWORD"
   ```

4. **Initial Data Refresh**:
   - After deployment, click "Refresh Data" in sidebar
   - Wait 5-10 minutes for initial data fetch
   - App will then load instantly from cache

> [!NOTE]
> **Dark Mode**: The app is pre-configured to force dark mode for all users via `.streamlit/config.toml`

## 📊 Features


### Data Management
- **Automatic Data Fetching**: Fetches historical stock data from TrueData API
- **Smart Caching**: Stores processed data in parquet files for fast loading
- **Refresh Controls**: Manual data refresh with customizable end dates

### Analysis Tabs

1. **Performance Overview**
   - Daily NAV charts comparing strategy vs benchmarks
   - Key performance metrics (Total Return, CAGR, Volatility, Sharpe Ratio, Max Drawdown)
   - Rolling return analysis

2. **Portfolio Composition**
   - Current holdings visualization
   - Historical stock presence tracking
   - Stock-level statistics and metrics

3. **Live Tracking**
   - Real-time portfolio monitoring using cached data
   - Current price tracking capability
   - Holdings analysis with entry prices and returns

4. **Historical Analysis**
   - Monthly portfolio composition evolution
   - Stock entry/exit patterns
   - Correlation analysis

5. **Reports**
   - Trade book generation
   - PDF report export
   - Data export (CSV/Excel)

## 🔧 Configuration

### TrueData Credentials

The app uses TrueData API for fetching market data. Credentials can be configured in two ways:

**Option 1: Streamlit Secrets (Recommended for deployment)**
Create `.streamlit/secrets.toml`:
```toml
[truedata]
username = "your_username"
password = "your_password"
```

**Option 2: Environment Variables (Local development)**
The app falls back to default credentials if secrets are not found.

### Excluded Symbols

To exclude specific stocks from the Live Tracking tab, edit the `EXCLUDED_SYMBOLS` list in `momentum_app.py`:
```python
EXCLUDED_SYMBOLS = [
    'SILVERBEES',  # Example: Exited stock
    # Add more symbols here
]
```

## 📝 Data Flow

1. **Initial Run**: App checks for cached data
2. **Data Refresh**: 
   - Fetches stock universe from `Ticker_Master.xlsx`
   - Retrieves historical data via TrueData API
   - Processes momentum calculations
   - Generates portfolio analytics
   - Saves results to `cache/` folder
3. **Subsequent Runs**: Loads data from cache for instant access

## 🎨 UI Features

- **Dark Blue Glassy Theme**: Modern, professional aesthetic
- **Responsive Design**: Works on desktop and mobile
- **Interactive Charts**: Powered by Plotly
- **Export Options**: PDF reports and data downloads

## 📦 Dependencies

**Core:**
- `momentum_app.py` - Main application
- `td_client.py` - Data fetching module
- `Ticker_Master.xlsx` - Stock universe

**Runtime (auto-generated):**
- `cache/` - Processed data storage

## 🔄 Updating Data

1. Click **"Refresh Data"** button in the sidebar
2. Optionally adjust the end date
3. Wait for data processing to complete
4. Cache will be updated automatically

## 💡 Tips

- **First Run**: May take 5-10 minutes to fetch and process all data
- **Cached Runs**: Load instantly from pre-computed cache files
- **Storage**: Cache files are lightweight parquet format (~10-20 MB total)
- **Refresh Frequency**: Update monthly or as needed

## 📄 License

This dashboard is part of the Momentum Strategy project.

## 🐛 Troubleshooting

**Import Error: td_client not found**
- Ensure `td_client.py` is in the same folder as `momentum_app.py`

**Data Fetch Errors**
- Check TrueData credentials
- Verify internet connection
- Check TrueData API quota

**Cache Issues**
- Delete `cache/` folder to force full data refresh
- Folder will be recreated automatically

---

**Last Updated**: February 2026
