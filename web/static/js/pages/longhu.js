// ====== 龙虎榜页面 ======

// 当前选中的日期
var currentLonghuDate = '';

async function loadLonghuDates() {
    var data = await api('/api/longhu-dates');
    if (!data || data.code !== 0) return;
    var dates = data.data || [];
    var sel = $('longhuDateSelect');
    if (!sel) return;
    var html = '';
    dates.forEach(function(d) {
        var label = d.date_key.substring(0, 4) + '-' + d.date_key.substring(4, 6) + '-' + d.date_key.substring(6, 8);
        html += '<option value="' + d.date_key + '">' + label + '（' + d.total_count + ' 只）</option>';
    });
    sel.innerHTML = html;
    if (dates.length > 0) {
        sel.value = dates[0].date_key;
        currentLonghuDate = dates[0].date_key;
    }
}

function switchLHPanel(name) {
    document.querySelectorAll('.lh-tab').forEach(function(tab) {
        tab.classList.toggle('active', tab.dataset.panel === name);
    });
    document.querySelectorAll('.lh-panel').forEach(function(p) {
        p.classList.toggle('active', p.id === 'panel-' + name);
    });
}

// 机构/北向买入榜行（代码、名称、日期、净买入、占比）
function renderBuyRow(item, i) {
    var code = item.stock_code || item.code || '';
    var name = item.stock_name || item.name || '';
    var netAmount = item.net_amount || 0;
    var ratio = item.net_buy_ratio || 0;
    var tradeDate = currentLonghuDate || '';
    if (tradeDate && tradeDate.length === 8) {
        tradeDate = tradeDate.substring(0, 4) + '-' + tradeDate.substring(4, 6) + '-' + tradeDate.substring(6, 8);
    }
    return '<tr>' +
        '<td>' + (i + 1) + '</td>' +
        '<td><span class="code-tag" onclick="openEastMoney(\'' + code + '\')">' + code + '</span></td>' +
        '<td>' + name + '</td>' +
        '<td>' + tradeDate + '</td>' +
        '<td style="color:#2ecc71;font-weight:600;">+' + netAmount.toFixed(2) + '</td>' +
        '<td style="color:#2ecc71;font-weight:600;">' + (ratio ? ratio.toFixed(4) + '%' : '-') + '</td>' +
        '</tr>';
}

// 机构/北向卖出榜行（代码、名称、日期、净卖出、占比）
function renderSellRow(item, i) {
    var code = item.stock_code || item.code || '';
    var name = item.stock_name || item.name || '';
    var netAmount = Math.abs(item.net_amount || 0);
    var ratio = Math.abs(item.net_buy_ratio || 0);
    var tradeDate = currentLonghuDate || '';
    if (tradeDate && tradeDate.length === 8) {
        tradeDate = tradeDate.substring(0, 4) + '-' + tradeDate.substring(4, 6) + '-' + tradeDate.substring(6, 8);
    }
    return '<tr>' +
        '<td>' + (i + 1) + '</td>' +
        '<td><span class="code-tag" onclick="openEastMoney(\'' + code + '\')">' + code + '</span></td>' +
        '<td>' + name + '</td>' +
        '<td>' + tradeDate + '</td>' +
        '<td style="color:#e74c3c;font-weight:600;">-' + netAmount.toFixed(2) + '</td>' +
        '<td style="color:#e74c3c;font-weight:600;">' + (ratio ? ratio.toFixed(4) + '%' : '-') + '</td>' +
        '</tr>';
}

function renderCategory(data, catKey, buyTbodyId, sellTbodyId, summaryId) {
    var cat = data && data[catKey];
    if (!cat) {
        $(buyTbodyId).innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $(sellTbodyId).innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        if (summaryId) $(summaryId).textContent = '';
        return;
    }

    // 汇总信息
    if (summaryId) {
        var totalNet = cat.total_net_amount || 0;
        var buyCount = (cat.top10_net_buy || []).length;
        var sellCount = (cat.top10_net_sell || []).length;
        $(summaryId).textContent = '净买入' + buyCount + '只，净卖出' + sellCount + '只，总净额' + totalNet.toFixed(2) + '万';
    }

    // 买入榜
    var buyItems = cat.top10_net_buy || cat.top5_net_buy || cat.top_5_net_buy || [];
    var buyHtml = '';
    buyItems.forEach(function(item, i) {
        buyHtml += renderBuyRow(item, i);
    });
    if (!buyHtml) buyHtml = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
    $(buyTbodyId).innerHTML = buyHtml;

    // 卖出榜
    var sellItems = cat.top10_net_sell || cat.top3_net_sell || cat.top_3_net_sell || [];
    var sellHtml = '';
    sellItems.forEach(function(item, i) {
        sellHtml += renderSellRow(item, i);
    });
    if (!sellHtml) sellHtml = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
    $(sellTbodyId).innerHTML = sellHtml;
}

function renderHotMoney(data) {
    var hm = data && data.hot_money_alpha;
    if (!hm) {
        $('lhHotBuyTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $('lhHotSellTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $('lhHotMoneySummary').textContent = '';
        $('lhTopBrokerages').innerHTML = '';
        $('lhFamousTraders').innerHTML = '';
        return;
    }

    var traders = hm.famous_hot_money_moves || [];
    $('lhHotMoneySummary').textContent = '买入营业部' + (hm.top10_net_buy_brokerages || []).length + '家，卖出营业部' + (hm.top10_net_sell_brokerages || []).length + '家，知名游资' + traders.length + '位';

    // 游资买入榜：代码=股票代码、名称=股票名称、卖家=游资名
    var buyTraders = traders.filter(function(t) { return t.action === '买' || t.amount >= 0; });
    var sellTraders = traders.filter(function(t) { return t.action === '卖' || t.amount < 0; });

    var buyHtml = '';
    buyTraders.forEach(function(t, i) {
        var code = (t.stock || '').split(/[\s+]/)[0] || t.stock || '';
        var stockName = '';
        // stock 可能是 "000001平安银行" 或 "000001 平安银行"
        var stockParts = (t.stock || '').split(/[\s+]/);
        if (stockParts.length >= 2) {
            stockName = stockParts.slice(1).join('');
        }
        var netAmount = Math.abs(t.amount || 0);
        var tradeDate = currentLonghuDate || '';
        if (tradeDate && tradeDate.length === 8) {
            tradeDate = tradeDate.substring(0, 4) + '-' + tradeDate.substring(4, 6) + '-' + tradeDate.substring(6, 8);
        }
        buyHtml += '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + code + '\')">' + code + '</span></td>' +
            '<td>' + stockName + '</td>' +
            '<td>' + tradeDate + '</td>' +
            '<td>' + (t.name || '') + '</td>' +
            '<td style="color:#2ecc71;font-weight:600;">+' + netAmount.toFixed(2) + '</td>' +
            '</tr>';
    });
    if (!buyHtml) buyHtml = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
    $('lhHotBuyTbody').innerHTML = buyHtml;

    var sellHtml = '';
    sellTraders.forEach(function(t, i) {
        var code = (t.stock || '').split(/[\s+]/)[0] || t.stock || '';
        var stockName = '';
        var stockParts = (t.stock || '').split(/[\s+]/);
        if (stockParts.length >= 2) {
            stockName = stockParts.slice(1).join('');
        }
        var netAmount = Math.abs(t.amount || 0);
        var tradeDate = currentLonghuDate || '';
        if (tradeDate && tradeDate.length === 8) {
            tradeDate = tradeDate.substring(0, 4) + '-' + tradeDate.substring(4, 6) + '-' + tradeDate.substring(6, 8);
        }
        sellHtml += '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + code + '\')">' + code + '</span></td>' +
            '<td>' + stockName + '</td>' +
            '<td>' + tradeDate + '</td>' +
            '<td>' + (t.name || '') + '</td>' +
            '<td style="color:#e74c3c;font-weight:600;">-' + netAmount.toFixed(2) + '</td>' +
            '</tr>';
    });
    if (!sellHtml) sellHtml = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
    $('lhHotSellTbody').innerHTML = sellHtml;

    // TOP10 买入营业部
    var buyBrokerages = hm.top10_net_buy_brokerages || [];
    var brHtml = '';
    if (buyBrokerages.length > 0) {
        brHtml = '<div class="result-table-wrap"><table><thead><tr><th>#</th><th>营业部</th><th>标签</th><th>净买入(万)</th></tr></thead><tbody>';
        buyBrokerages.forEach(function(b, i) {
            brHtml += '<tr><td>' + (i + 1) + '</td><td>' + (b.brokerage || '') + '</td><td>' + (b.tag || '-') + '</td><td style="color:#2ecc71;font-weight:600;">+' + (b.net_amount || 0).toFixed(2) + '</td></tr>';
        });
        brHtml += '</tbody></table></div>';
    }

    // TOP10 卖出营业部
    var sellBrokerages = hm.top10_net_sell_brokerages || [];
    if (sellBrokerages.length > 0) {
        brHtml += '<div style="margin-top:10px;"><div style="font-size:13px;font-weight:600;margin-bottom:6px;">📉 卖出营业部 TOP10</div>';
        brHtml += '<div class="result-table-wrap"><table><thead><tr><th>#</th><th>营业部</th><th>标签</th><th>净卖出(万)</th></tr></thead><tbody>';
        sellBrokerages.forEach(function(b, i) {
            brHtml += '<tr><td>' + (i + 1) + '</td><td>' + (b.brokerage || '') + '</td><td>' + (b.tag || '-') + '</td><td style="color:#e74c3c;font-weight:600;">-' + Math.abs(b.net_amount || 0).toFixed(2) + '</td></tr>';
        });
        brHtml += '</tbody></table></div></div>';
    }
    $('lhTopBrokerages').innerHTML = brHtml;

    // 知名游资详情
    var famousHtml = '';
    if (traders.length > 0) {
        famousHtml = '<div class="lh-famous">';
        traders.forEach(function(t) {
            var color = (t.action === '买' || t.amount >= 0) ? '#2ecc71' : '#e74c3c';
            var sign = (t.action === '买' || t.amount >= 0) ? '买入' : '卖出';
            famousHtml += '<div class="lh-famous-item">' +
                '<div><span class="trader-name">' + (t.name || '') + '</span></div>' +
                '<div class="trader-stock">📈 ' + (t.stock || '') + ' ' + sign + ' ' + Math.abs(t.amount || 0).toFixed(2) + '万</div>' +
                '</div>';
        });
        famousHtml += '</div>';
    }
    $('lhFamousTraders').innerHTML = famousHtml;
}

function renderHighlightStocks(data) {
    var el = $('lhHighlightContent');
    var items = data && data.highlight_stocks || [];
    if (items.length === 0) {
        el.innerHTML = '<div style="color:var(--text-secondary);font-size:13px;">暂无数据</div>';
        return;
    }
    var html = '';
    items.forEach(function(item) {
        var code = item.stock_code || item.code || '';
        var name = item.stock_name || item.name || '';
        html += '<div class="lh-highlight">' +
            '<div><span class="stock-name">' + name + ' (' + code + ')</span></div>' +
            '<div style="margin-top:4px;">' + (item.analysis || '') + '</div>' +
            '</div>';
    });
    el.innerHTML = html;
}

function renderFlatList(data, buyTbodyId, sellTbodyId, summaryId) {
    // 扁平列表渲染（东方财富 API 格式）
    if (!data || data.length === 0) {
        $(buyTbodyId).innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $(sellTbodyId).innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        if (summaryId) $(summaryId).textContent = '';
        return;
    }

    var buyItems = data.filter(function(s) { return s.net_buy > 0; }).sort(function(a, b) { return b.net_buy - a.net_buy; });
    var sellItems = data.filter(function(s) { return s.net_buy < 0; }).sort(function(a, b) { return a.net_buy - b.net_buy; });

    if (summaryId) {
        $(summaryId).textContent = '净买入' + buyItems.length + '只，净卖出' + sellItems.length + '只';
    }

    // 买入榜
    var buyHtml = '';
    buyItems.forEach(function(item, i) {
        var code = item.code || '';
        var name = item.name || '';
        var netAmount = item.net_buy || 0;
        var ratio = item.net_buy_ratio || 0;
        var tradeDate = item.trade_date || '';
        if (tradeDate && tradeDate.length === 8) {
            tradeDate = tradeDate.substring(0, 4) + '-' + tradeDate.substring(4, 6) + '-' + tradeDate.substring(6, 8);
        }
        buyHtml += '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + code + '\')">' + code + '</span></td>' +
            '<td>' + name + '</td>' +
            '<td>' + tradeDate + '</td>' +
            '<td style="color:#2ecc71;font-weight:600;">+' + netAmount.toFixed(2) + '</td>' +
            '<td style="color:#2ecc71;font-weight:600;">' + (ratio ? ratio.toFixed(4) + '%' : '-') + '</td>' +
            '</tr>';
    });
    if (!buyHtml) buyHtml = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
    $(buyTbodyId).innerHTML = buyHtml;

    // 卖出榜
    var sellHtml = '';
    sellItems.forEach(function(item, i) {
        var code = item.code || '';
        var name = item.name || '';
        var netAmount = Math.abs(item.net_buy || 0);
        var ratio = Math.abs(item.net_buy_ratio || 0);
        var tradeDate = item.trade_date || '';
        if (tradeDate && tradeDate.length === 8) {
            tradeDate = tradeDate.substring(0, 4) + '-' + tradeDate.substring(4, 6) + '-' + tradeDate.substring(6, 8);
        }
        sellHtml += '<tr>' +
            '<td>' + (i + 1) + '</td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + code + '\')">' + code + '</span></td>' +
            '<td>' + name + '</td>' +
            '<td>' + tradeDate + '</td>' +
            '<td style="color:#e74c3c;font-weight:600;">-' + netAmount.toFixed(2) + '</td>' +
            '<td style="color:#e74c3c;font-weight:600;">' + (ratio ? ratio.toFixed(4) + '%' : '-') + '</td>' +
            '</tr>';
    });
    if (!sellHtml) sellHtml = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
    $(sellTbodyId).innerHTML = sellHtml;
}

async function loadLonghu() {
    var url = '/api/longhu';
    if (currentLonghuDate) {
        url += '?date_key=' + currentLonghuDate;
    }
    var data = await api(url);
    if (!data || data.code !== 0) return;

    var deepseekRaw = data.deepseek_raw || null;
    var flatData = data.data || [];

    if (deepseekRaw && deepseekRaw.institution_tracking) {
        // DeepSeek 格式：嵌套结构
        renderCategory(deepseekRaw, 'institution_tracking', 'lhInstBuyTbody', 'lhInstSellTbody', 'lhInstSummary');
        renderCategory(deepseekRaw, 'hs_connect_tracking', 'lhHSBuyTbody', 'lhHSSellTbody', 'lhHSConnectSummary');
        renderHotMoney(deepseekRaw);
        renderHighlightStocks(deepseekRaw);
    } else if (flatData && flatData.length > 0) {
        // 东方财富 API 格式：扁平列表
        renderFlatList(flatData, 'lhInstBuyTbody', 'lhInstSellTbody', 'lhInstSummary');
        // 清空其他面板
        $('lhHSBuyTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $('lhHSSellTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $('lhHSConnectSummary').textContent = '';
        $('lhHotBuyTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $('lhHotSellTbody').innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        $('lhHotMoneySummary').textContent = '';
        $('lhTopBrokerages').innerHTML = '';
        $('lhFamousTraders').innerHTML = '';
        $('lhHighlightContent').innerHTML = '<div style="color:var(--text-secondary);font-size:13px;">暂无数据</div>';
    } else {
        // 无数据
        ['lhInstBuyTbody', 'lhInstSellTbody', 'lhHSBuyTbody', 'lhHSSellTbody', 'lhHotBuyTbody', 'lhHotSellTbody'].forEach(function(id) {
            $(id).innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);">暂无数据</td></tr>';
        });
        ['lhInstSummary', 'lhHSConnectSummary', 'lhHotMoneySummary'].forEach(function(id) {
            $(id).textContent = '';
        });
        $('lhTopBrokerages').innerHTML = '';
        $('lhFamousTraders').innerHTML = '';
        $('lhHighlightContent').innerHTML = '<div style="color:var(--text-secondary);font-size:13px;">暂无数据</div>';
    }
}

function onLonghuDateChange() {
    var sel = $('longhuDateSelect');
    if (sel) {
        currentLonghuDate = sel.value;
        loadLonghu();
    }
}

async function updateLonghu() {
    var btn = $('btnUpdateLonghu');
    btn.disabled = true;
    btn.innerHTML = '⏳ 更新中...';
    $('longhuStatus').textContent = '正在更新龙虎榜数据...';
    var data = await api('/api/update-longhu', { method: 'POST' });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        $('longhuStatus').textContent = '更新成功';
        await loadLonghuDates();
        loadLonghu();
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
        $('longhuStatus').textContent = '❌ ' + data.message;
    } else {
        showToast('❌ 更新失败', 'error');
        $('longhuStatus').textContent = '❌ 更新失败';
    }
    btn.disabled = false;
    btn.innerHTML = '🔄 更新龙虎榜';
}

// 页面加载时自动加载
(async function initLonghu() {
    await loadLonghuDates();
    loadLonghu();
})();
