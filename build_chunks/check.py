import re
c = open('index.html', encoding='utf-8').read()
print('charset present:', 'charset="UTF-8"' in c)
print('spread_pct present:', 'spread_pct' in c)
# Check which non-ASCII chars exist (should only be html entities rendered as unicode glyphs from PowerShell copying)
sample = [(i, ord(c[i]), c[i]) for i in range(len(c)) if 0x80 < ord(c[i]) < 0x100][:20]
print('Non-ASCII latin chars:', sample)
# Check for actual garbled CFTC-style corruption
garbled = re.findall(r'Ā·|â€|δΎ', c)
print('Garbled sequences:', len(garbled), garbled[:3] if garbled else '')
