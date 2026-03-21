import json, sys

with open('index.html', 'r', encoding='utf-8') as f:
    text = f.read()

# Crosshair Plugin and Tooltip Element (Features 1 & 2)
plugin_code = """
const crosshairPlugin = {
    id: 'crosshair',
    afterDraw(chart) {
        if (!chart._crosshairX) return;
        const ctx = chart.ctx;
        const area = chart.chartArea;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(chart._crosshairX, area.top);
        ctx.lineTo(chart._crosshairX, area.bottom);
        ctx.strokeStyle = 'rgba(255,255,255,0.4)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.restore();
    },
    afterEvent(chart, args) {
        const event = args.event;
        if (event.type === 'mousemove') {
            chart._crosshairX = event.x;
            chart.update('none');
        }
        if (event.type === 'mouseout') {
            chart._crosshairX = null;
            chart.update('none');
        }
    }
};
Chart.register(crosshairPlugin);

const tooltipEl = document.createElement('div');
tooltipEl.id = 'chart-tooltip';
tooltipEl.style.cssText = `
    position: fixed;
    background: #1a1f2e;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 12px 16px;
    pointer-events: none;
    z-index: 9999;
    font-size: 12px;
    color: #e2e8f0;
    min-width: 220px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    display: none;
`;
document.body.appendChild(tooltipEl);

function buildTooltipHTML(type, instKey, trader, idx) {
    const instLabel = INSTRUMENT_LABELS[instKey] ?? instKey ?? 'Unknown';
    const d = getTooltipData(instKey, trader, idx);
    if (!d) return `<div class="tt-header">${instLabel}</div><div class="tt-row">No data available</div>`;

    const fmt = (v, dec = 0, pre = '', suf = '') =>
        (v === null || v === undefined) ? '—' : 
        (typeof v === 'string' ? v : `${pre}${Number(v).toLocaleString('en-US', {minimumFractionDigits: dec, maximumFractionDigits: dec})}${suf}`);

    if (type === 'multi_trader') {
       const inst = CFTC_DATA.instruments[instKey];
       const traders = ['managed_money', 'swap_dealers', 'producers', 'other_reportables', 'non_reportables'];
       const lines = traders.map(tk => {
           const net = inst?.[tk]?.net?.[idx];
           const pct = inst?.[tk]?.pct_of_oi?.[idx];
           return net !== null ? `<div class="tt-row" style="color:${TRADER_COLOURS[tk]}"><span>${TRADER_LABELS[tk]}</span><span>${fmt(net)} (${fmt(pct,1,'','%')})</span></div>` : '';
       }).join('');
       return `
            <div class="tt-header">${instLabel}</div>
            <div class="tt-divider"></div>
            ${lines}
            <div class="tt-divider"></div>
            <div class="tt-row"><span>Price</span><span>${fmt(d.price,2,'$')}</span></div>
            <div class="tt-row"><span>Regime</span><span>${d.oi_regime}</span></div>
            <div class="tt-divider"></div>
            <div class="tt-row" style="justify-content:center; color:var(--text3); font-size:9px;">📅 ${d.date}</div>
       `;
    }

    if (type === 'net_pos_vs_price') {
        return `
            <div class="tt-header">${instLabel}</div>
            <div class="tt-divider"></div>
            <div class="tt-row"><span>Net Position</span><span>${fmt(d.net)}</span></div>
            <div class="tt-row"><span>Long</span><span>${fmt(d.long)}</span></div>
            <div class="tt-row"><span>Short</span><span>${fmt(d.short)}</span></div>
            <div class="tt-divider"></div>
            <div class="tt-row"><span>Z-Score</span><span>${fmtZ(d.z_score)} (${fmtPct(d.pct_rank)})</span></div>
            <div class="tt-row"><span>COT Index</span><span>${fmt(d.cot_3yr,0,'','%')}</span></div>
            <div class="tt-divider"></div>
            <div class="tt-row"><span>Price</span><span>$${fmt(d.price,2)}</span></div>
            <div class="tt-row"><span>OI Regime</span><span>${d.oi_regime}</span></div>
            <div class="tt-divider"></div>
            <div class="tt-row" style="justify-content:center; color:var(--text3); font-size:9px;">📅 ${d.date}</div>
        `;
    }

    if (type === 'rolling_corr') return `<div class="tt-header">${instLabel}</div><div class="tt-row"><span>20w Corr</span><span>${fmt(d.net, 2)}</span></div><div class="tt-row"><span>Regime</span><span>${d.oi_regime}</span></div><div class="tt-divider"></div><div class="tt-row" style="justify-content:center; color:var(--text3); font-size:9px;">📅 ${d.date}</div>`;
    if (type === 'seasonal') return `<div class="tt-header">${instLabel}</div><div class="tt-row"><span>Net Pos</span><span>${fmt(d.net)}</span></div><div class="tt-row"><span>5Y Avg</span><span>${fmt(d.long)}</span></div><div class="tt-divider"></div><div class="tt-row" style="justify-content:center; color:var(--text3); font-size:9px;">📅 ${d.date}</div>`;
    
    return `<div class="tt-header">${instLabel}</div><div class="tt-row"><span>Value</span><span>${fmt(d.net)}</span></div><div class="tt-divider"></div><div class="tt-row" style="justify-content:center; color:var(--text3); font-size:9px;">📅 ${d.date}</div>`;
}

function externalTooltipHandler(context) {
    const { chart, tooltip } = context;
    if (tooltip.opacity === 0) { tooltipEl.style.display = 'none'; return; }
    const idx = tooltip.dataPoints?.[0]?.dataIndex; if (idx === undefined) return;
    const type = chart.userData?.type || 'net_pos_vs_price';
    const inst = chart.userData?.instrumentKey || activeInstrument;
    const trader = chart.userData?.traderKey || activeTrader;
    
    tooltipEl.innerHTML = buildTooltipHTML(type, inst, trader, idx);
    tooltipEl.style.display = 'block';
    const canvasRect = chart.canvas.getBoundingClientRect();
    const x = canvasRect.left + tooltip.caretX;
    const y = canvasRect.top + tooltip.caretY;
    const left = x + 240 > window.innerWidth - 20 ? x - 240 - 10 : x + 15;
    tooltipEl.style.left = left + 'px';
    tooltipEl.style.top = Math.max(10, y - 60) + 'px';
}

function resetChartZoom(id) {
    const chart = Chart.getChart(id);
    if(chart) chart.resetZoom();
}

"""

text = text.replace(
    "const CHART_BASE = {",
    plugin_code + "const CHART_BASE = {"
)

text = text.replace(
"""plugins:{legend:{display:false},tooltip:{enabled:false}},""",
"""plugins:{
  legend:{display:false},
  tooltip:{enabled:false, external: externalTooltipHandler},
  zoom:{
    zoom:{wheel:{enabled:true},pinch:{enabled:true},mode:'x'},
    pan:{enabled:true,mode:'x'}
  }
},"""
)

with open('index.html.tmp3', 'w', encoding='utf-8') as f:
    f.write(text)
print("done")
