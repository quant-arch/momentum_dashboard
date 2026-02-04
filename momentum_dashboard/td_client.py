import requests
import time
import logging
import pandas as pd
import struct
import lz4.block
import threading
from io import StringIO
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure Logging
logger = logging.getLogger(__name__)

class TrueDataClient:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.auth_url = "https://auth.truedata.in/token"
        self.hist_url = "https://history.truedata.in"
        self.access_token = None
        self.token_expiry = datetime.min
        self.auth_lock = threading.RLock() # Thread safety lock
        
        # Setup Session with Retries
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=2, # Increased backoff
            status_forcelist=[403, 429, 500, 502, 503, 504], # Added 403 to retry list strictly
            allowed_methods=["HEAD", "GET", "POST"]
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _authenticate(self):
        """Authenticates and refreshes token if needed."""
        with self.auth_lock: # Ensure only one thread authenticates at a time
            if self.access_token and datetime.now() < self.token_expiry:
                return

            payload = {
                "username": self.username,
                "password": self.password,
                "grant_type": "password"
            }
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            
            try:
                logger.info("Authenticating with TrueData...")
                # Allow slightly longer timeout for auth
                response = self.session.post(self.auth_url, data=payload, headers=headers, timeout=15) 
                
                # Special handling for 403 during auth to print details
                if response.status_code == 403:
                    logger.error(f"Auth 403 Forbidden: {response.text}")
                    
                response.raise_for_status()
                data = response.json()
                
                self.access_token = data['access_token']
                # Set expiry with buffer (15s)
                self.token_expiry = datetime.now() + timedelta(seconds=data['expires_in'] - 15)
                logger.info("Authentication Successful.")
                
            except requests.exceptions.HTTPError as e:
                logger.error(f"Authentication Failed: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Authentication Error: {e}")
                raise

    def decompress_data(self, data):
        try:
            if not data:
                return ""
            uncom_length = struct.unpack('<I', data[:4])[0]
            com_length = struct.unpack('<I', data[4:8])[0]
            
            if com_length != uncom_length:
                dc = lz4.block.decompress(data[8:], uncom_length)
                return dc.decode('utf-8')
            return data[8:].decode('utf-8')
        except Exception as e:
            # If decompression fails, it might be plain text error if header check failed
            logger.error(f"Decompression error: {e}")
            try:
                return data.decode('utf-8')
            except:
                return ""

    def get_historic_data(self, ticker, duration=None, bar_size="eod", end_time=None):
        """
        Fetches historical data.
        duration: e.g. '10 D', '1 Y'
        bar_size: 'eod', '1 min', etc.
        """
        # Ensure we have a valid token before proceeding
        self._authenticate()
        
        # Calculate Start/End times
        if end_time is None:
            end_dt = datetime.now()
        else:
            end_dt = pd.to_datetime(end_time)
            
        start_dt = self._calculate_start_time(duration, end_dt)
        
        # Format for API: YYMMDDTHH:MM:SS
        to_str = end_dt.strftime('%y%m%dT23:59:59')
        from_str = start_dt.strftime('%y%m%dT00:00:00')
        
        # Prepare Request
        endpoint = "getbars"
        params = {
            'symbol': ticker,
            'interval': bar_size,
            'response': 'csv',
            'comp': 'true' # LZ4 compression
        }
        
        # Handle manual query string for from/to as per original lib quirks
        params['from'] = from_str
        params['to'] = to_str
        
        # Use simple session get, allowing retries to handle temporary issues
        # Auth header must be refreshed if token is renewed, but 'self.access_token' is dynamic
        # However, if we fail 401/403 inside the loop, we might need to re-auth.
        # But 'requests' retry logic won't re-call _authenticate unless we hook it.
        # For now, rely on initial auth validity.
        
        # Actually, for robustness, if we get 401/403, we should maybe retry auth?
        # But let's stick to the locking first which should solve the root cause (parallel Auth spam).
        
        headers = {'Authorization': f'Bearer {self.access_token}'}
        url = f"{self.hist_url}/{endpoint}"
        
        try:
            response = self.session.get(url, headers=headers, params=params, timeout=20)
            
            if response.status_code != 200:
                logger.error(f"API Error {ticker}: {response.status_code} - {response.text}")
                return None
                
            # Decompress
            csv_text = self.decompress_data(response.content)
            
            if not csv_text or "timestamp" not in csv_text:
                if "No data" in csv_text:
                    logger.warning(f"No data found for {ticker}")
                else:
                    logger.warning(f"Invalid response for {ticker}: {csv_text[:100]}")
                return None
                
            # Parse CSV
            df = pd.read_csv(StringIO(csv_text))
            
            # Standardize Columns
            # API returns: timestamp,open,high,low,close,volume,oi
            df.rename(columns={'timestamp': 'Date'}, inplace=True)
            df['Date'] = pd.to_datetime(df['Date'])
            df['Ticker'] = ticker
            
            # Capitalize columns to match system expectation
            df.rename(columns={
                'open': 'Open', 'high': 'High', 'low': 'Low', 
                'close': 'Close', 'volume': 'Volume', 'oi': 'OI'
            }, inplace=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Fetch Exception {ticker}: {e}")
            return None

    def _calculate_start_time(self, duration, end_dt):
        """Parses duration string '10 Y' etc."""
        if not duration:
            return end_dt - timedelta(days=365) # Default
            
        parts = duration.split()
        val = int(parts[0])
        unit = parts[1].upper()
        
        if unit == 'D':
            return end_dt - timedelta(days=val)
        if unit == 'W':
            return end_dt - timedelta(weeks=val)
        if unit == 'M':
            return end_dt - timedelta(days=val*30) # Approx
        if unit == 'Y':
            return end_dt - timedelta(days=val*365)
            
        return end_dt - timedelta(days=365)
