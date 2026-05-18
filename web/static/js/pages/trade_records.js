// ====== 实盘记录页面 ======
var _currentBatchId = '';

async function loadTradeBatches() {
    var data = await api('/api/trade/batches');
    if (!data || data.code !== 0) return;
    var batches = data.data || [];
    var tbody = $('tradeBatchTbody');
    var html = '';
    batches.forEach(function(b) {
        var statusLabel = b.status === 'settled' ? '<span style="color:#2ecc71;">✅ 已结算</span>' : '<span style="color:#f39c12;">⏳ 持仓中</span>';
        html += '<tr>' +
            '<td style="font-size:11px;">' + b.batch_id + '</td>' +
            '<td>' + b.buy_date + '</td>' +
            '<td>' + b.sell_date + '</td>' +
            '<td>' + b.stock_count + '</td>' +
            '<td>' + (b.win_count || 0) + '</td>' +
            '<td>' + (b.loss_count || 0) + '</td>' +
            '<td>' + (b.win_rate != null ? b.win_rate + '%' : '-') + '</td>' +
            '<td>' + (b.avg_return != null ? b.avg_return + '%' : '-') + '</td>' +
            '<td>' + statusLabel + '</td>' +
            '<td><button class="btn btn-ghost btn-sm" onclick="showTradeDetail(\'' + b.batch_id + '\')">📋 详情</button></td>' +
            '</tr>';
    });
    tbody.innerHTML = html;
    $('tradeBatchesArea').style.display = 'block';
}

async function showTradeDetail(batchId) {
    _currentBatchId = batchId;
    var data = await api('/api/trade/records?batch_id=' + encodeURIComponent(batchId));
    if (!data || data.code !== 0) return;
    var records = data.data || [];
    $('tradeDetailTitle').textContent = '批次: ' + batchId + ' (' + records.length + ' 只)';
    var tbody = $('tradeRecordTbody');
    var html = '';
    records.forEach(function(r, i) {
        var statusLabel = r.status === 'settled' ? '<span style="color:#2ecc71;">✅ 已结算</span>' : '<span style="color:#f39c12;">⏳ 持仓中</span>';
        var retColor = (r.return_pct || 0) >= 0 ? '#2ecc71' : '#e74c3c';
        var retLabel = r.return_pct != null ? (r.return_pct >= 0 ? '+' : '') + r.return_pct + '%' : '-';
        html += '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + r.code + '\')">' + r.code + '</span></td>' +
            '<td>' + r.name + '</td>' +
            '<td>' + (r.score || '-') + '</td>' +
            '<td>' + (r.buy_price != null ? r.buy_price.toFixed(2) : '<input type="number" step="0.01" id="bp-' + r.id + '" placeholder="买入价" style="width:80px;padding:2px 4px;font-size:11px;">') + '</td>' +
            '<td>' + (r.shares || '-') + '</td>' +
            '<td>' + (r.sell_price != null ? r.sell_price.toFixed(2) : '-') + '</td>' +
            '<td style="color:' + retColor + ';font-weight:600;">' + retLabel + '</td>' +
            '<td>' + statusLabel + '</td>' +
            '<td>' +
                (r.status === 'holding' && !r.buy_price ?
                    '<button class="btn btn-ghost btn-sm" onclick="updateBuyPrice(' + r.id + ')">💲 填价</button>' : '') +
            '</td>' +
            '</tr>';
    });
    tbody.innerHTML = html;
    $('tradeDetailArea').style.display = 'block';
}

async function updateBuyPrice(recordId) {
    var input = $('bp-' + recordId);
    if (!input) return;
    var price = parseFloat(input.value);
    if (isNaN(price) || price <= 0) {
        showToast('请输入有效的买入价', 'error');
        return;
    }
    var data = await api('/api/trade/update-buy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'record_id=' + recordId + '&buy_price=' + price + '&shares=0'
    });
    if (data && data.code === 0) {
        showToast('✅ 买入价已更新', 'success');
        showTradeDetail(_currentBatchId);
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

async function createTradeBatch() {
    var scoredData = await api('/api/ai-stock-picks?source=scored');
    if (!scoredData || scoredData.code !== 0 || !scoredData.data || scoredData.data.length === 0) {
        showToast('❌ 没有综合评分数据，请先在 AI 选股页面计算综合评分', 'error');
        return;
    }
    var top10 = scoredData.data.slice(0, 10);
    var data = await api('/api/trade/create-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stocks: top10 })
    });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        loadTradeBatches();
        if (data.data) {
            showTradeDetail(data.data.batch_id);
        }
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

async function settleBatch() {
    if (!_currentBatchId) {
        showToast('请先选择一个批次', 'error');
        return;
    }
    if (!confirm('确定结算批次 ' + _currentBatchId + ' 吗？')) return;
    var data = await api('/api/trade/settle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'batch_id=' + encodeURIComponent(_currentBatchId)
    });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        showTradeDetail(_currentBatchId);
        loadTradeBatches();
        loadTradeStats();
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

async function loadTradeStats() {
    var data = await api('/api/trade/stats');
    if (!data || data.code !== 0) return;
    var stats = data.data;
    $('tsTotal').textContent = stats.overall.total_trades || 0;
    $('tsWins').textContent = stats.overall.wins || 0;
    $('tsLosses').textContent = stats.overall.losses || 0;
    $('tsWinRate').textContent = (stats.overall.win_rate || 0) + '%';
    $('tsAvgRet').textContent = (stats.overall.avg_return || 0) + '%';
    $('tsBatches').textContent = stats.overall.batch_count || 0;
    $('tradeStatsArea').style.display = 'block';
}

// 页面加载时自动加载批次列表
(async function initTrade() {
    loadTradeBatches();
})();
