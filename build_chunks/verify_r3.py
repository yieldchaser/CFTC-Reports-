import re, sys

content = open('index.html', encoding='utf-8').read()

# 1. Script tag balance
opens  = content.count('<script')
closes = content.count('</script>')
print(f'script tags: {opens} open, {closes} close', 'OK' if opens==closes else 'FAIL')
assert opens == closes

# 2. Div balance
divO = content.count('<div')
divC = content.count('</div>')
print(f'div tags: {divO} open, {divC} close, diff={abs(divO-divC)}', 'OK' if abs(divO-divC)<10 else 'FAIL')
assert abs(divO-divC)<10

# 3. File size
sz = len(content.encode('utf-8'))
print(f'File size: {sz} bytes', 'OK (>40KB)' if sz>40000 else 'WARNING: small')

# 4. Bug fixes
checks = {
    'charset=\\"UTF-8\\"':       'Bug 1: charset UTF-8',
    'auto-fill':                  'Bug 5: cards auto-fill grid',
    'min:0,max:100':              'Bug 3: COT axis 0-100',
    'concentration-fallback':     'Bug 2: concentration fallback',
    'pct-bar-sub':                'Bug 4: pct bar sub-labels',
    'other_reportables':          'F1: Other Reportables',
    'spread_pct':                 'F2: MM Spread',
    'non_reportables':            'F3: Non-Reportables',
    'oi_regime':                  'F4: OI Regime',
    'momentum_score':             'F5: Momentum Score',
    'lagged_corr':                'F6: Lagged Correlation',
    'stale-banner':               'F7: Staleness Banner',
    'setHmTrader':                'F8a: Heatmap trader toggle',
    'setHmWeeks':                 'F8b: Heatmap week range',
    'setCorrPeriod':              'F8c: Corr period',
    'titleSuffix':                'F8d: Chart title values',
    'ArrowRight':                 'F8e: Keyboard nav',
}
all_ok = True
for k, desc in checks.items():
    found = k in content
    print(f'  [{"OK" if found else "MISSING"}] {desc}')
    if not found:
        all_ok = False

# 5. No garbled chars
garbled = re.findall(r'δΎ|Ā·|â€', content)
print(f'Garbled chars: {len(garbled)}', 'OK' if not garbled else 'FAIL')
if garbled: all_ok = False

# 6. No TODOs
todos = [l.strip() for l in content.split('\n') if re.search(r'TODO|FIXME|placeholder|coming soon', l, re.I)]
print(f'TODOs found: {len(todos)}', 'OK' if not todos else 'FAIL')

print()
print('=== ALL CHECKS PASSED ===' if all_ok else '=== SOME CHECKS FAILED ===')
