chunks = [
    'build_chunks/chunk1_head_css.html',
    'build_chunks/chunk2_body_structure.html',
    'build_chunks/chunk3_js_data_utils.html',
    'build_chunks/chunk4_js_overview.html',
    'build_chunks/chunk5_js_by_instrument.html',
    'build_chunks/chunk6_js_multitrader.html',
    'build_chunks/chunk7_js_init.html',
]
parts = []
for p in chunks:
    with open(p, encoding='utf-8') as f:
        parts.append(f.read())
combined = '\n'.join(parts)
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(combined)
print(f'Written: {len(combined.encode("utf-8"))} bytes')
