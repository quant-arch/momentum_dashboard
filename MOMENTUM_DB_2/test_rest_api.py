import os
import requests
from datetime import datetime, timedelta

username = os.getenv("TRUEDATA_USERNAME")
password = os.getenv("TRUEDATA_PASSWORD")
symbols = ['^NIFTY6535', 'NIFTY6535', 'NIFTY 6535']
# We need an access token first
token_url = 'https://auth.truedata.in/token'
data = {'username': username, 'password': password}
try:
    resp = requests.post(token_url, json=data, timeout=10)
    if resp.status_code == 200:
        token = resp.json().get('token')
        headers = {'Authorization': f'Bearer {token}'}
        for sym in symbols:
            hist_url = f'https://api.truedata.in/getHistoricData?symbol={sym}&duration=30 D&bar_size=EOD'
            res = requests.get(hist_url, headers=headers, timeout=10)
            print(f"{sym} -> HTTP {res.status_code}")
            if res.status_code == 200:
                print(res.text[:200])
    else:
        print("Auth failed:", resp.text)
except Exception as e:
    print("Error:", e)
