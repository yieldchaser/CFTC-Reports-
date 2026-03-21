import io, requests, pandas as pd

url = (
    "https://publicreporting.cftc.gov/resource/72hh-3qpy.csv"
    "?commodity_name=NATURAL%20GAS&$limit=20000"
    "&$order=report_date_as_yyyy_mm_dd%20DESC"
)
raw = requests.get(url, timeout=90).text
df = pd.read_csv(io.StringIO(raw), low_memory=False)
print("Columns:", list(df.columns[:6]))
col = [c for c in df.columns if 'market' in c.lower() and 'exchange' in c.lower()]
print("Market col:", col)
market_col = col[0] if col else 'market_and_exchange_names'
ng_markets = sorted([m for m in df[market_col].unique()
                     if any(x in str(m) for x in ['NAT GAS','HENRY HUB','NATURAL GAS'])])
print(f"\nAvailable NG markets ({len(ng_markets)}):")
for m in ng_markets:
    count = len(df[df[market_col] == m])
    print(f"  {count:4d} rows  {m}")
