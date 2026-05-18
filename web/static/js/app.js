// ====== 工具函数 ======
function $(id) { return document.getElementById(id); }

function openEastMoney(code) {
    var prefix = code.startsWith('6') ? 'sh' : 'sz';
    window.open('https://quote.eastmoney.com/' + prefix + code + '.html', '_blank');
}

function showToast(msg, type) {
    var el = $('toastContainer');
    el.textContent = msg;
    el.className = 'toast ' + (type || 'info') + ' show';
    clearTimeout(el._timer);
    el._timer = setTimeout(function(){ el.classList.remove('show'); }, 3000);
}

async function api(url, opts) {
    try {
        var resp = await fetch(url, opts || {});
        return await resp.json();
    } catch(e) {
        console.error('API error:', url, e);
        return null;
    }
}

// ====== 折叠面板 ======
function toggleCollapse(id, headerEl) {
    var body = document.getElementById(id);
    var arrow = document.getElementById('arrow-' + id);
    if (!body || !arrow) return;
    var isOpen = body.classList.contains('open');
    if (isOpen) {
        body.classList.remove('open');
        arrow.classList.remove('open');
    } else {
        body.classList.add('open');
        arrow.classList.add('open');
    }
}

// ====== 状态栏 ======
async function loadStatus() {
    var data = await api('/api/status');
    if (!data || data.code !== 0) return;
    var s = data.data;
    if ($('statStocks')) $('statStocks').textContent = s.stock_count || '-';
    if ($('statDate')) $('statDate').textContent = s.latest_date || '-';
    if ($('statRecords')) $('statRecords').textContent = s.total_records || '-';
    if ($('statTime')) $('statTime').textContent = '⏱ ' + (s.server_time || '');
}

// ====== 初始化 ======
loadStatus();
setInterval(loadStatus, 10000);
