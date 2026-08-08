import os
#!/usr/bin/env python3
"""
Test script to check TrueData API connectivity and data availability.
Tests a variety of ticker symbols to determine if the issue is systemic or symbol-specific.
"""

import time
import logging
from truedata import TD_hist

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test tickers: mix of popular stocks, ETFs, and the ones that failed
test_tickers = [
    # Popular liquid stocks
    'RELIANCE',
    'TCS',
    'INFY',
    'HDFC',
    'ICICIBANK',
    # ETFs
    'GOLDBEES',
    'LIQUIDCASE',
    'CPSEETF',
    'NEXT50IETF',
    # Stocks that failed in the previous run
    'ABCAPITAL',
    'ANANDRATHI',
    'ANANTRAJ',
    'BANKBARODA',
]

def test_single_ticker(td_hist, ticker, duration='5 Y', bar_size='EOD'):
    """Test fetching data for a single ticker."""
    try:
        logger.info(f'Fetching data for {ticker}...')
        df = td_hist.get_historic_data([ticker], duration=duration, bar_size=bar_size)
        
        if df is None or df.empty:
            logger.warning(f'  ❌ {ticker}: No data returned (empty/None)')
            return False
        else:
            logger.info(f'  ✅ {ticker}: Success ({len(df)} rows, columns: {list(df.columns)[:5]}...)')
            return True
    except Exception as e:
        logger.error(f'  ❌ {ticker}: Exception - {type(e).__name__}: {str(e)[:100]}')
        return False

def main():
    """Run connectivity tests."""
    logger.info('=' * 70)
    logger.info('TrueData Connectivity Test')
    logger.info('=' * 70)
    
    # Initialize connection
    username = os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")
    
    try:
        td_hist = TD_hist(username, password)
        logger.info('✅ Connected to TrueData successfully\n')
    except Exception as e:
        logger.error(f'❌ Failed to connect to TrueData: {e}')
        return
    
    # Test each ticker
    results = {}
    for ticker in test_tickers:
        success = test_single_ticker(td_hist, ticker)
        results[ticker] = success
        time.sleep(0.15)  # Avoid throttling
    
    # Summary
    logger.info('\n' + '=' * 70)
    logger.info('Summary')
    logger.info('=' * 70)
    successful = sum(1 for v in results.values() if v)
    total = len(results)
    logger.info(f'Successful: {successful}/{total}')
    
    logger.info('\nFailed tickers:')
    for ticker, success in results.items():
        if not success:
            logger.info(f'  - {ticker}')
    
    if successful == total:
        logger.info('\n✅ All tests passed! TrueData API is working normally.')
    elif successful == 0:
        logger.error('\n❌ All tests failed! TrueData API appears to be down or unreachable.')
    else:
        logger.warning(f'\n⚠️ Partial failure: {successful}/{total} succeeded. Some tickers may be unavailable.')

if __name__ == '__main__':
    main()
