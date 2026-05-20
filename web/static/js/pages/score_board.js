// ====== 综合评分排行榜页面 ======
var SCORE_PAGE_SIZE = 20;
var scorePage = 1;
var _scoreData = [];
var _currentDateKey = '';

function renderScoreResult() {
    var data = _scoreData;
    var totalPages = Math.max(1, Math.ceil(data.length / SCORE_PAGE_SIZE));
    var start = (scorePage - 1) * SCORE_PAGE_SIZE;
    var end = Math.min(start + SCORE_PAGE_SIZE, data.length);
    var pageData = data.slice(start, end);

    var tbody = $('scoreResultTbody');
    var html = '';
    pageData.forEach(function(s) {
        var rankClass = s.rank === 1 ? 'rank-1' : s.rank === 2 ? 'rank-2' : s.rank === 3 ? 'rank-3' : 'rank-other';
        var scoreVal = (s.total_score != null) ? s.total_score.toFixed(1) : (s.score != null ? s.score.toFixed(1) : '-');
        var pctVal = (s.avg_pct_5d != null) ? (s.avg_pct_5d >= 0 ? '+' : '') + s.avg_pct_5d.toFixed(2) + '%' : '-';
        var pctClass = (s.avg_pct_5d || 0) >= 0 ? 'up' : 'down';
        var volVal = (s.vol_ratio != null) ? s.vol_ratio.toFixed(2) : '-';
        var priceVal = (s.latest_close != null) ? s.latest_close.toFixed(2) : '-';
        var sourceLabels = '';
        if (s.sources && Array.isArray(s.sources)) {
            var uniqueSources = [];
            var seenSrc = {};
            s.sources.forEach(function(src) {
                if (!seenSrc[src]) {
                    seenSrc[src] = true;
                    uniqueSources.push(src);
                }
            });
            sourceLabels = uniqueSources.join(', ');
        } else if (s.source) {
            sourceLabels = s.source;
        } else {
            sourceLabels = '-';
        }
        var rsiDiv = s.rsi_divergence;
        var rsiLabel = '-';
        var rsiColor = '#8888aa';
        if (rsiDiv === 1) { rsiLabel = '🟢 底背离'; rsiColor = '#2ecc71'; }
        else if (rsiDiv === 0) { rsiLabel = '⚪ 无背离'; rsiColor = '#8888aa'; }
        else if (rsiDiv === -1) { rsiLabel = '🔴 顶背离'; rsiColor = '#e74c3c'; }

        var strategyLabel = '-';
        var strategyColor = '#8888aa';
        if (s.strategy_type === 'A') { strategyLabel = '🚀 突破型'; strategyColor = '#e74c3c'; }
        else if (s.strategy_type === 'B') { strategyLabel = '🛡️ 埋伏型'; strategyColor = '#2ecc71'; }

        var support1 = (s.support_1 != null) ? s.support_1.toFixed(2) : '-';
        var support2 = (s.support_2 != null) ? s.support_2.toFixed(2) : '-';
        var resist1 = (s.resistance_1 != null) ? s.resistance_1.toFixed(2) : '-';
        var resist2 = (s.resistance_2 != null) ? s.resistance_2.toFixed(2) : '-';
        var buyPrice = (s.buy_price != null) ? s.buy_price.toFixed(2) : '-';
        var sellPrice = (s.sell_price != null) ? s.sell_price.toFixed(2) : '-';
        var stopLoss = (s.stop_loss != null) ? s.stop_loss.toFixed(2) : '-';

        var buyColor = (s.buy_price != null && s.latest_close != null && s.buy_price < s.latest_close) ? '#2ecc71' : '#8888aa';
        var sellColor = (s.sell_price != null && s.latest_close != null && s.sell_price > s.latest_close) ? '#2ecc71' : '#8888aa';
        var stopColor = (s.stop_loss != null && s.latest_close != null && s.stop_loss < s.latest_close) ? '#e74c3c' : '#8888aa';

        var scoreDetail = s.score_detail || '';
        var reasonText = s.reason || '-';
        var reasonEscaped = reasonText.replace(/"/g, '&#34;').replace(/</g, '<').replace(/>/g, '>').replace(/'/g, '&#39;');
        // 评分说明保留换行符，tooltip 中显示多行
        var detailForTip = scoreDetail.replace(/"/g, '&#34;').replace(/</g, '<').replace(/>/g, '>').replace(/'/g, '&#39;');
        // 表格中显示时，换行符替换为空格（单行省略）
        var detailForDisplay = scoreDetail.replace(/\n/g, ' | ');

        html += '<tr>' +
            '<td><span class="rank-num ' + rankClass + '">' + s.rank + '</span></td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + s.code + '\')">' + s.code + '</span></td>' +
            '<td><strong>' + s.name + '</strong></td>' +
            '<td>' + (s.sector || '-') + '</td>' +
            '<td style="font-size:10px;">' + sourceLabels + '</td>' +
            '<td><span style="color:' + strategyColor + ';font-weight:600;font-size:10px;">' + strategyLabel + '</span></td>' +
            '<td class="price-cell"><strong>' + priceVal + '</strong></td>' +
            '<td class="price-cell ' + pctClass + '">' + pctVal + '</td>' +
            '<td class="price-cell">' + volVal + '</td>' +
            '<td class="price-cell"><span style="color:' + rsiColor + ';font-weight:600;">' + rsiLabel + '</span></td>' +
            '<td class="price-cell"><strong>' + scoreVal + '</strong></td>' +
            '<td class="price-cell green">' + support1 + '</td>' +
            '<td class="price-cell green">' + support2 + '</td>' +
            '<td class="price-cell red">' + resist1 + '</td>' +
            '<td class="price-cell red">' + resist2 + '</td>' +
            '<td class="price-cell" style="color:' + buyColor + ';font-weight:600;">' + buyPrice + '</td>' +
            '<td class="price-cell" style="color:' + sellColor + ';font-weight:600;">' + sellPrice + '</td>' +
            '<td class="price-cell" style="color:' + stopColor + ';font-weight:600;">' + stopLoss + '</td>' +
            '<td class="tip-trigger" data-tip="' + detailForTip + '" style="font-size:10px;color:var(--text-secondary);max-width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.3;">' + (detailForDisplay || '-') + '</td>' +
            '<td class="reason-cell tip-trigger" data-tip="' + reasonEscaped + '">' + reasonText + '</td>' +
            '</tr>';
    });
    tbody.innerHTML = html;

    var pagEl = $('scoreResultPagination');
    if (totalPages <= 1) {
        pagEl.innerHTML = '';
        return;
    }
    var ph = '<button onclick="scoreGoPage(' + (scorePage - 1) + ')" ' + (scorePage <= 1 ? 'disabled' : '') + '>\u25c0</button>';
    for (var i = 1; i <= totalPages; i++) {
        if (i === scorePage) {
            ph += '<button class="active">' + i + '</button>';
        } else if (i === 1 || i === totalPages || Math.abs(i - scorePage) <= 2) {
            ph += '<button onclick="scoreGoPage(' + i + ')">' + i + '</button>';
        } else if (Math.abs(i - scorePage) === 3) {
            ph += '<button disabled>...</button>';
        }
    }
    ph += '<button onclick="scoreGoPage(' + (scorePage + 1) + ')" ' + (scorePage >= totalPages ? 'disabled' : '') + '>\u25b6</button>';
    ph += '<span class="page-info">' + scorePage + '/' + totalPages + '</span>';
    pagEl.innerHTML = ph;
}

function scoreGoPage(page) {
    var data = _scoreData;
    var totalPages = Math.max(1, Math.ceil(data.length / SCORE_PAGE_SIZE));
    if (page < 1 || page > totalPages) return;
    scorePage = page;
    renderScoreResult();
}

async function loadScoreDates() {
    var data = await api('/api/score-board/dates');
    if (!data || data.code !== 0) return;
    var dates = data.data || [];
    var sel = $('scoreDateSelect');
    sel.innerHTML = '';
    dates.forEach(function(d) {
        var opt = document.createElement('option');
        opt.value = d.date_key;
        opt.textContent = d.date_key + ' (' + d.count + '只)';
        sel.appendChild(opt);
    });
    if (dates.length > 0) {
        sel.value = _currentDateKey || dates[0].date_key;
    }
}

async function switchScoreDate() {
    var sel = $('scoreDateSelect');
    var dateKey = sel.value;
    if (!dateKey) return;
    _currentDateKey = dateKey;
    scorePage = 1;
    var data = await api('/api/score-board/load?date_key=' + encodeURIComponent(dateKey));
    if (data && data.code === 0) {
        _scoreData = data.data || [];
        $('scoreSourceLabel').textContent = '综合评分';
        $('scoreTotalCount').textContent = _scoreData.length;
        renderScoreResult();
    }
}

async function computeStrongest() {
    var btn = $('btnComputeScore');
    btn.disabled = true;
    btn.innerHTML = '⏳ 计算中...';
    showToast('正在计算最强排名...', 'info');

    var models = ['deepseek', 'kimi', 'gemini', 'grok', 'chatgpt'];
    var allStocks = [];
    var seen = new Set();

    function flattenStocks(data, format) {
        var result = [];
        if (format === 'themes' && data && data.length > 0 && data[0].theme_name) {
            data.forEach(function(theme) {
                (theme.stocks || []).forEach(function(s) {
                    result.push({
                        code: s.code, name: s.name,
                        sector: theme.theme_name || '',
                        reason: s.reason || theme.core_drivers || '',
                    });
                });
            });
        } else {
            (data || []).forEach(function(s) {
                result.push({
                    code: s.code, name: s.name,
                    sector: s.sector || '', reason: s.reason || '',
                });
            });
        }
        return result;
    }

    for (var m of models) {
        var data = await api('/api/ai-stock-picks?source=' + m);
        if (data && data.code === 0 && data.data) {
            var flatStocks = flattenStocks(data.data, data.format);
            flatStocks.forEach(function(s) {
                var key = s.code;
                if (!seen.has(key)) {
                    seen.add(key);
                    var weight = (m === 'deepseek') ? 0.2 : 1.0;
                    allStocks.push({
                        code: s.code, name: s.name,
                        sector: s.sector || '', reason: s.reason || '',
                        sources: [m], weight: weight
                    });
                } else {
                    var existing = allStocks.find(function(x) { return x.code === key; });
                    if (existing) {
                        if (existing.sources.indexOf(m) === -1) {
                            existing.sources.push(m);
                        }
                        if (m !== 'deepseek') existing.weight = 1.0;
                    }
                }
            });
        }
    }

    if (allStocks.length === 0) {
        showToast('❌ 没有股票数据，请先运行 AI 分析', 'error');
        btn.disabled = false;
        btn.innerHTML = '📊 计算综合评分';
        return;
    }

    var result = await api('/api/ai-score-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stocks: allStocks })
    });

    if (result && result.code === 0) {
        _scoreData = result.data;
        scorePage = 1;
        _currentDateKey = '';
        $('scoreSourceLabel').textContent = '综合评分';
        $('scoreTotalCount').textContent = result.data.length;
        renderScoreResult();
        
        // 自动保存到数据库
        var saveResult = await api('/api/score-board/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ stocks: result.data })
        });
        
        if (saveResult && saveResult.code === 0) {
            _currentDateKey = saveResult.date_key;
            showToast('✅ 计算完成，共 ' + result.data.length + ' 只股票，已保存到 ' + saveResult.date_key, 'success');
            // 刷新日期列表
            await loadScoreDates();
            var sel = $('scoreDateSelect');
            if (sel) sel.value = _currentDateKey;
        } else {
            showToast('✅ 计算完成，共 ' + result.data.length + ' 只股票', 'success');
        }
    } else if (result) {
        showToast('❌ ' + result.message, 'error');
    } else {
        showToast('❌ 计算失败', 'error');
    }
    btn.disabled = false;
    btn.innerHTML = '📊 计算综合评分';
}

// ====== 独立 tooltip 逻辑（避免被父元素 overflow 截断） ======
var _tipBox = null;
function initTipBox() {
    if (_tipBox) return;
    _tipBox = document.createElement('div');
    _tipBox.className = 'tip-box';
    document.body.appendChild(_tipBox);
}
function showTip(el, text) {
    if (!_tipBox) initTipBox();
    _tipBox.textContent = text;
    _tipBox.style.display = 'block';
    var rect = el.getBoundingClientRect();
    var top = rect.top - _tipBox.offsetHeight - 6;
    if (top < 4) top = rect.bottom + 6;
    _tipBox.style.left = Math.max(4, Math.min(rect.left, window.innerWidth - 404)) + 'px';
    _tipBox.style.top = top + 'px';
}
function hideTip() {
    if (_tipBox) _tipBox.style.display = 'none';
}
// 全局事件委托监听 tip-trigger
document.addEventListener('mouseover', function(e) {
    var el = e.target.closest('.tip-trigger');
    if (el) {
        var tip = el.getAttribute('data-tip');
        if (tip) showTip(el, tip);
    }
});
document.addEventListener('mouseout', function(e) {
    var el = e.target.closest('.tip-trigger');
    if (el) hideTip();
});

// 页面加载时自动恢复数据
(async function initScoreBoard() {
    // 加载日期列表
    await loadScoreDates();
    
    // 加载最新评分数据
    var data = await api('/api/score-board/load');
    if (data && data.code === 0 && data.data && data.data.length > 0) {
        _scoreData = data.data;
        _currentDateKey = data.date_key || '';
        scorePage = 1;
        $('scoreSourceLabel').textContent = '综合评分';
        $('scoreTotalCount').textContent = data.data.length;
        renderScoreResult();
        
        // 同步日期选择器
        var sel = $('scoreDateSelect');
        if (sel && _currentDateKey) sel.value = _currentDateKey;
    }
})();
