// ====== 数据更新页面 ======

// 加载数据库概览
async function loadDbOverview() {
    try {
        var data = await api('/api/db-overview');
        if (data && data.code === 0) {
            $('statDays').textContent = data.data.days;
            $('statRows').textContent = data.data.rows;
            $('statStart').textContent = data.data.start_date || '-';
            $('statEnd').textContent = data.data.end_date || '-';
            $('dbOverviewSub').textContent = '最后更新: ' + (data.data.last_update || '-');
        }
    } catch (e) {
        console.error('加载数据库概览失败', e);
    }
}

// 更新日志显示
function updateLogs(logs) {
    var container = $('logContainer');
    if (!logs || logs.length === 0) {
        container.innerHTML = '<div class="log-info">等待更新任务启动...</div>';
        return;
    }
    var html = '';
    for (var i = 0; i < logs.length; i++) {
        var log = logs[i];
        var cls = 'log-info';
        if (log.startsWith('✓')) cls = 'log-ok';
        else if (log.startsWith('✗')) cls = 'log-fail';
        html += '<div class="' + cls + '">' + escapeHtml(log) + '</div>';
    }
    container.innerHTML = html;
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

// 轮询更新状态
var statusPollTimer = null;

function startStatusPoll() {
    if (statusPollTimer) return;
    statusPollTimer = setInterval(async function() {
        try {
            var st = await api('/api/update-status');
            if (st && st.code === 0) {
                var data = st.data;
                $('updateProgressText').textContent = data.progress || '运行中...';
                if (data.logs) updateLogs(data.logs);
                if (!data.running) {
                    stopStatusPoll();
                    loadDbOverview();
                    setTimeout(function() { $('updateProgressRow').style.display = 'none'; }, 5000);
                }
            }
        } catch (e) {
            console.error('轮询状态失败', e);
        }
    }, 2000);
}

function stopStatusPoll() {
    if (statusPollTimer) {
        clearInterval(statusPollTimer);
        statusPollTimer = null;
    }
}

// 触发更新
async function triggerUpdate(apiPath, modeName) {
    var btnMap = {
        '/api/update-full': 'btnUpdateFull',
        '/api/update-incremental': 'btnUpdateIncremental',
        '/api/update-realtime': 'btnUpdateRealtime',
    };
    var btn = $(btnMap[apiPath]);
    btn.disabled = true;
    btn.innerHTML = '⏳ ' + modeName + '中...';
    showToast('正在' + modeName + '...', 'info');
    $('updateProgressRow').style.display = '';
    $('updateProgressText').textContent = '启动中...';
    $('logContainer').innerHTML = '<div class="log-info">启动' + modeName + '...</div>';
    
    // 先发请求触发更新
    var data = await api(apiPath, { method: 'POST' });
    
    if (data && data.code !== 0) {
        showToast('❌ ' + data.message, 'error');
        $('updateProgressText').textContent = '❌ ' + data.message;
        btn.disabled = false;
        btn.innerHTML = btnMap[apiPath] === 'btnUpdateFull' ? '📦 全量' : 
                       btnMap[apiPath] === 'btnUpdateIncremental' ? '📥 增量' : '⚡ 实时';
        return;
    }
    
    // 启动轮询
    startStatusPoll();
    
    // 等轮询结束恢复按钮
    var checkDone = setInterval(function() {
        if (!statusPollTimer) {
            clearInterval(checkDone);
            btn.disabled = false;
            btn.innerHTML = btnMap[apiPath] === 'btnUpdateFull' ? '📦 全量' : 
                           btnMap[apiPath] === 'btnUpdateIncremental' ? '📥 增量' : '⚡ 实时';
        }
    }, 1000);
}

// 全量更新
async function updateFull() {
    triggerUpdate('/api/update-full', '全量更新');
}

// 增量更新
async function updateIncremental() {
    triggerUpdate('/api/update-incremental', '增量更新');
}

// 实时更新
async function updateRealtime() {
    triggerUpdate('/api/update-realtime', '实时更新');
}

// 页面加载时加载数据库概览
loadDbOverview();
