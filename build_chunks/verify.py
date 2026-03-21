import re, sys

content = open('index.html', encoding='utf-8').read()
opens  = content.count('<script')
closes = content.count('</script>')
print(f'script tags: {opens} open, {closes} close')
assert opens == closes, f'MISMATCHED: {opens} vs {closes}'

divO = content.count('<div')
divC = content.count('</div>')
print(f'div tags: {divO} open, {divC} close, diff={abs(divO-divC)}')
assert abs(divO-divC)<10

checks = {
    'heatmap-body':          'heatmap grid (Bug 1)',
    'trader-wrap':           'trader-filter hide (Bug 4)',
    'normaliseByOI':         'normalise toggle (Bug 3)',
    'cot_index':             'COT Index (E1)',
    'composite_scores':      'composite score (E6)',
    'getSignalLabel':        'signal labels (E6)',
    'seasonal_avg_by_week':  'seasonal overlay (E2)',
    'change_net':            'weekly flow (E3)',
    'concentration':         'concentration chart (E4)',
    'correlation_matrix':    'corr matrix (E5)',
    'downloadCSV':           'CSV export (E7)',
    'extremes':              'historical extremes (E8)',
}
for k, desc in checks.items():
    found = k in content
    status = 'OK' if found else 'MISSING'
    print(f'  [{status}] {desc}')
    if not found:
        print(f'    ^ searching for: {k}', file=sys.stderr)

# Bug 2 boundary fix
bug2 = '>= 1.5' in content or '>= 1.5' in content or '<= -1.5' in content or '<=-1.5' in content
print(f'  [{"OK" if bug2 else "MISSING"}] >= boundary fix (Bug 2)')

print('\nALL CHECKS PASSED' if all(k in content for k in checks) and bug2 else '\nSOME CHECKS FAILED')
