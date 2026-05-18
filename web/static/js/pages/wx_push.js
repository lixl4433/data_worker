// ====== 微信推送页面 ======
async function loadWxPushList() {
    var data = await api('/api/wx-push');
    if (!data || data.code !== 0) return;
    var items = data.data || [];
    var tbody = $('wxPushTbody');
    var html = '';
    items.forEach(function(item) {
        html += '<tr>' +
            '<td>' + item.id + '</td>' +
            '<td>' + item.wx_id + '</td>' +
            '<td>' + (item.remark || '-') + '</td>' +
            '<td>' + (item.created_at || '-') + '</td>' +
            '<td><button class="btn btn-danger btn-sm" onclick="deleteWxPush(' + item.id + ')">🗑 删除</button></td>' +
            '</tr>';
    });
    tbody.innerHTML = html;
}

async function addWxPush() {
    var wxId = $('wxIdInput').value.trim();
    var remark = $('wxRemarkInput').value.trim();
    if (!wxId) {
        showToast('请输入微信号', 'error');
        return;
    }
    var data = await api('/api/wx-push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'wx_id=' + encodeURIComponent(wxId) + '&remark=' + encodeURIComponent(remark)
    });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        $('wxIdInput').value = '';
        $('wxRemarkInput').value = '';
        loadWxPushList();
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

async function deleteWxPush(id) {
    if (!confirm('确定删除该微信号吗？')) return;
    var data = await api('/api/wx-push/' + id, { method: 'DELETE' });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        loadWxPushList();
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

async function recomputeAndPush() {
    var btn = $('btnRecomputePush');
    btn.disabled = true;
    btn.innerHTML = '⏳ 计算并推送中...';
    showToast('正在计算强势股票并推送微信...', 'info');
    var data = await api('/api/recompute-strong', { method: 'POST' });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
    btn.disabled = false;
    btn.innerHTML = '📤 计算并推送';
}

// 页面加载时自动加载列表
(async function initWx() {
    loadWxPushList();
})();
