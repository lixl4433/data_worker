// ====== 实盘交易记录 ======

function $(id) { return document.getElementById(id); }
function hide(id) { $(id).style.display = 'none'; }

// 加载交易列表
async function loadTrades() {
    var data = await api('/api/trade/list');
    if (!data || data.code !== 0) return;
    var records = data.data || [];
    var holding = records.filter(function(r) { return r.status === 'holding'; }).length;
    var closed = records.filter(function(r) { return r.status === 'closed'; }).length;
    $('hc').textContent = holding;
    $('cc').textContent = closed;

    var html = '';
    records.forEach(function(r) {
        var sl = r.strategy_type === 'A' ? '<span style="color:#e74c3c;font-weight:600;">🚀A</span>'
                 : r.strategy_type === 'B' ? '<span style="color:#2ecc71;font-weight:600;">🛡️B</span>' : '-';
        var stl = r.status === 'closed' ? '<span style="color:#2ecc71;">✅ 已平仓</span>' : '<span style="color:#f39c12;">⏳ 持仓</span>';
        var rc = (r.return_pct || 0) >= 0 ? '#2ecc71' : '#e74c3c';
        var rl = r.return_pct != null ? (r.return_pct >= 0 ? '+' : '') + r.return_pct + '%' : '-';
        var nl = r.net_return_pct != null ? (r.net_return_pct >= 0 ? '+' : '') + r.net_return_pct + '%' : '-';
        var hl = r.holding_days_actual != null ? r.holding_days_actual + '天' : '-';
        var sok = r.stop_loss ? r.stop_loss.toFixed(2) : '-';
        var tpk = r.take_profit ? r.take_profit.toFixed(2) : '-';
        var safe_name = r.name || '';
        var safe_code = r.code || '';

        html += '<tr>' +
            '<td>' + r.id + '</td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + safe_code + '\')">' + safe_code + '</span></td>' +
            '<td>' + safe_name + '</td>' +
            '<td>' + sl + '</td>' +
            '<td>' + (r.score || '-') + '</td>' +
            '<td>' + (r.entry_date || '-') + '</td>' +
            '<td>' + (r.buy_price != null ? r.buy_price.toFixed(2) : '-') + '</td>' +
            '<td>' + (r.shares || '-') + '</td>' +
            '<td style="color:#dc2626;">' + sok + '</td>' +
            '<td style="color:#16a34a;">' + tpk + '</td>' +
            '<td>' + (r.exit_date || '-') + '</td>' +
            '<td>' + (r.sell_price != null ? r.sell_price.toFixed(2) : '-') + '</td>' +
            '<td style="color:' + rc + ';font-weight:600;">' + rl + '</td>' +
            '<td style="color:' + rc + ';">' + nl + '</td>' +
            '<td>' + hl + '</td>' +
            '<td>' + stl + '</td>' +
            '<td style="font-size:11px;">' +
                (r.status === 'holding'
                    ? '<button class="btn btn-success btn-sm" onclick="showClose(' + r.id + ')">💰</button> '
                    : '') +
                '<button class="btn btn-ghost btn-sm" onclick="editTrade(' + r.id + ')">✏️</button> ' +
                '<button class="btn btn-ghost btn-sm" onclick="delTrade(' + r.id + ')" style="color:#e74c3c;">🗑️</button>' +
            '</td></tr>';
    });
    if (!records.length) {
        html = '<tr><td colspan="17" style="text-align:center;color:#999;padding:40px;">暂无交易记录<br>点击「从评分导入」或「手动录入」添加</td></tr>';
    }
    $('tbody').innerHTML = html;
}

// 从评分导入
async function showImport() {
    var p = $('importPanel');
    if (p.style.display !== 'none') { p.style.display = 'none'; return; }
    p.style.display = 'block';
    $('importDate').value = new Date().toISOString().split('T')[0];

    var data = await api('/api/score-board/load');
    if (!data || data.code !== 0 || !data.data) {
        $('importList').innerHTML = '<span style="color:#999;">暂无评分数据</span>';
        return;
    }
    var stocks = data.data.filter(function(s) { return s.score != null && s.score > -9999; });
    stocks.sort(function(a, b) { return (b.score || 0) - (a.score || 0); });

    var html = '<table class="import-table"><tr><th><input type="checkbox" id="selAll" checked onchange="document.querySelectorAll(\'.cb\').forEach(function(c){c.checked=this.checked},this)"></th><th>#</th><th>代码</th><th>名称</th><th>策略</th><th>评分</th><th>现价</th><th>止损</th><th>止盈</th><th>股数</th></tr>';
    stocks.slice(0, 10).forEach(function(s, i) {
        var st = s.strategy_type === 'A' ? '🚀A' : s.strategy_type === 'B' ? '🛡️B' : '-';
        html += '<tr><td><input type="checkbox" class="cb" checked></td>' +
            '<td>' + (i+1) + '</td>' +
            '<td class="imp-code">' + s.code + '</td>' +
            '<td class="imp-name">' + (s.name||'') + '</td>' +
            '<td class="imp-strategy">' + (s.strategy_type||'') + '</td>' +
            '<td class="imp-score">' + (s.score||'') + '</td>' +
            '<td>' + (s.latest_close || '-') + '</td>' +
            '<td class="imp-stop">' + (s.stop_loss||'') + '</td>' +
            '<td class="imp-take">' + (s.sell_price||'') + '</td>' +
            '<td><input type="number" class="imp-shares" value="100" style="width:60px;padding:2px 4px;font-size:11px;"></td></tr>';
    });
    html += '</table>';
    $('importList').innerHTML = html;
}

async function doImport() {
    var rows = document.querySelectorAll('#importList .cb:checked');
    if (!rows.length) { showToast('请至少选一只股票', 'error'); return; }
    var stocks = [];
    rows.forEach(function(cb) {
        var tr = cb.closest('tr');
        var tds = tr.querySelectorAll('td');
        stocks.push({
            code: tr.querySelector('.imp-code').textContent.trim(),
            name: tr.querySelector('.imp-name').textContent.trim(),
            strategy_type: tr.querySelector('.imp-strategy').textContent.trim(),
            score: parseFloat(tr.querySelector('.imp-score').textContent) || 0,
            buy_price: parseFloat(tr.querySelectorAll('td')[6].textContent) * 0.99 || 0,
            stop_loss: parseFloat(tr.querySelector('.imp-stop').textContent) || null,
            take_profit: parseFloat(tr.querySelector('.imp-take').textContent) || null,
            shares: parseInt(tr.querySelector('.imp-shares').value) || 100,
        });
    });

    var entryDate = $('importDate').value || new Date().toISOString().split('T')[0];
    $('btnImport').disabled = true;
    $('btnImport').textContent = '导入中...';
    var data = await api('/api/trade/import-from-scored', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stocks: stocks, entry_date: entryDate}),
    });
    $('btnImport').disabled = false;
    $('btnImport').textContent = '📥 导入';
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        hide('importPanel');
        loadTrades();
    } else if (data) { showToast('❌ ' + data.message, 'error'); }
}

// 手动添加
function showAddModal() {
    $('addModalTitle').textContent = '手动录入交易';
    ['f_code','f_name','f_sector','f_buy','f_shares','f_score','f_stop','f_take','f_note'].forEach(function(id) { $(id).value = ''; });
    $('f_entry').value = new Date().toISOString().split('T')[0];
    $('f_hold').value = 5;
    $('f_follow').value = '1';
    $('f_strategy').value = '';
    $('btnSave').dataset.id = '';
    $('addModal').style.display = 'flex';
}

function editTrade(id) {
    api('/api/trade/detail?id=' + id).then(function(data) {
        if (!data || data.code !== 0) return;
        var r = data.data;
        $('addModalTitle').textContent = '编辑交易 #' + r.id;
        $('f_code').value = r.code || '';
        $('f_name').value = r.name || '';
        $('f_sector').value = r.sector || '';
        $('f_strategy').value = r.strategy_type || '';
        $('f_buy').value = r.buy_price || '';
        $('f_shares').value = r.shares || '';
        $('f_entry').value = r.entry_date || '';
        $('f_score').value = r.score || '';
        $('f_stop').value = r.stop_loss || '';
        $('f_take').value = r.take_profit || '';
        $('f_hold').value = r.hold_days_recommended || 5;
        $('f_follow').value = r.followed_system != null ? r.followed_system : 1;
        $('f_note').value = r.note || '';
        $('btnSave').dataset.id = r.id;
        $('addModal').style.display = 'flex';
    });
}

async function saveTrade() {
    var id = $('btnSave').dataset.id;
    var body = {
        code: $('f_code').value.trim(),
        name: $('f_name').value.trim(),
        sector: $('f_sector').value.trim(),
        strategy_type: $('f_strategy').value,
        buy_price: parseFloat($('f_buy').value),
        shares: parseInt($('f_shares').value) || 0,
        entry_date: $('f_entry').value,
        score: parseFloat($('f_score').value) || null,
        stop_loss: parseFloat($('f_stop').value) || null,
        take_profit: parseFloat($('f_take').value) || null,
        hold_days_recommended: parseInt($('f_hold').value) || 5,
        followed_system: parseInt($('f_follow').value),
        note: $('f_note').value.trim(),
    };
    if (!body.code || !body.name || !body.buy_price || !body.shares) {
        showToast('请填写代码、名称、买入价和股数', 'error'); return;
    }
    var url = '/api/trade/create';
    if (id) { body.id = parseInt(id); url = '/api/trade/update'; }
    var data = await api(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (data && data.code === 0) { showToast('✅ ' + data.message, 'success'); hide('addModal'); loadTrades(); }
    else if (data) { showToast('❌ ' + data.message, 'error'); }
}

// 平仓
function showClose(id) {
    api('/api/trade/detail?id=' + id).then(function(data) {
        if (!data || data.code !== 0) return;
        var r = data.data;
        $('closeInfo').innerHTML = '<strong>' + r.code + ' ' + r.name + '</strong>' +
            ' | 买入: ' + (r.buy_price || '-') + ' | 股数: ' + (r.shares || '-');
        $('f_sell').value = r.take_profit || '';
        $('f_sell').dataset.id = r.id;
        $('f_exit').value = new Date().toISOString().split('T')[0];
        $('f_fees').value = 0;
        $('closeModal').style.display = 'flex';
    });
}

async function doClose() {
    var id = parseInt($('f_sell').dataset.id);
    var sp = parseFloat($('f_sell').value);
    var ed = $('f_exit').value;
    var fees = parseFloat($('f_fees').value) || 0;
    if (!sp) { showToast('请输入卖出价', 'error'); return; }
    var data = await api('/api/trade/close', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id:id, sell_price:sp, exit_date:ed, fees:fees}) });
    if (data && data.code === 0) { showToast('✅ 平仓成功 ' + (data.data.return_pct >= 0 ? '+' : '') + data.data.return_pct + '%', 'success'); hide('closeModal'); loadTrades(); loadStats(); }
    else if (data) { showToast('❌ ' + data.message, 'error'); }
}

// 删除
async function delTrade(id) {
    if (!confirm('确认删除？')) return;
    var data = await api('/api/trade/delete', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id:id}) });
    if (data && data.code === 0) { showToast('已删除', 'info'); loadTrades(); }
}

// 统计
async function toggleStats() {
    var p = $('statsPanel');
    if (p.style.display !== 'none') { p.style.display = 'none'; return; }
    var data = await api('/api/trade/stats');
    if (!data || data.code !== 0) return;
    var d = data.data;
    var o = d.overall || {};
    var h = '<div class="stat-card">' +
        '<div class="stat-item"><div class="stat-label">总交易</div><div class="stat-value">' + (o.total||0) + '</div></div>' +
        '<div class="stat-item"><div class="stat-label">胜</div><div class="stat-value green">' + (o.wins||0) + '</div></div>' +
        '<div class="stat-item"><div class="stat-label">负</div><div class="stat-value red">' + (o.losses||0) + '</div></div>' +
        '<div class="stat-item"><div class="stat-label">胜率</div><div class="stat-value orange">' + (o.win_rate||0) + '%</div></div>' +
        '<div class="stat-item"><div class="stat-label">均收益</div><div class="stat-value">' + (o.avg_return||0) + '%</div></div>' +
        '<div class="stat-item"><div class="stat-label">累计</div><div class="stat-value">' + (o.cum_return||0) + '%</div></div>' +
        '</div>';

    var s = d.by_strategy || {};
    var sk = Object.keys(s);
    if (sk.length) {
        h += '<div style="margin-top:8px; display:flex; gap:12px; flex-wrap:wrap; font-size:12px; color:var(--text-secondary);">';
        sk.forEach(function(k) {
            h += '<span style="background:#f1f5f9;padding:4px 8px;border-radius:4px;">策略 ' + k + ': 胜率 <strong>' + s[k].win_rate + '%</strong> (' + s[k].wins + '/' + s[k].total + ') 均收益 <strong>' + (s[k].avg_return >= 0 ? '+' : '') + s[k].avg_return + '%</strong></span>';
        });
        h += '</div>';
    }

    var m = d.by_month || {};
    var mk = Object.keys(m).sort();
    if (mk.length) {
        h += '<div style="margin-top:8px; font-size:11px; color:var(--text-secondary);">📅 月度胜率:<br>';
        mk.forEach(function(k) {
            h += k + ': ' + m[k].win_rate + '% (' + m[k].wins + '/' + m[k].total + ')<br>';
        });
        h += '</div>';
    }

    if (d.holding_count) { h += '<div style="margin-top:8px; font-size:12px;">🟢 当前持仓: ' + d.holding_count + ' 笔</div>'; }
    p.innerHTML = h;
    p.style.display = 'block';
}

// 初始化
(function init() { loadTrades(); })();
