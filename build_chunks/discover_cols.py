import io, pandas as pd, requests

raw = requests.get(
    'https://publicreporting.cftc.gov/resource/72hh-3qpy.csv'
    '?commodity_name=NATURAL%20GAS&$limit=100', timeout=60
).text
df = pd.read_csv(io.StringIO(raw), low_memory=False)
cols = [c for c in df.columns if 'other' in c.lower() or 'nonrept' in c.lower()]
print('Other/NonRept columns:')
for c in sorted(cols):
    print(' ', c)
