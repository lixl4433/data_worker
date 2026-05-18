// ====== AI 选股页面（5 模型卡片） ======
var _modelPages = {};
var _modelData = {};
var MODEL_PAGE_SIZE = 10;

function renderModelTable(model, stocks, format) {
    if (!_modelPages[model]) _modelPages[model] = 1;
    
    var tbody = $('table-' + model);
    var pagEl = $('pag-' + model);
    
    if (format === 'themes' && stocks && stocks.length > 0 && stocks[0].theme_name) {
        var html = '';
        stocks.forEach(function(theme) {
            var themeName = theme.theme_name || '';
            var stage = theme.stage || '';
            var coreDrivers = theme.core_drivers || '';
            var stageBadge = '';
            if (stage === '发酵期') stageBadge = '<span style="color:#3498db;font-weight:600;font-size:10px;">🌱 发酵期</span>';
            else if (stage === '爆发期') stageBadge = '<span style="color:#e74c3c;font-weight:600;font-size:10px;">🔥 爆发期</span>';
            else if (stage === '衰退期') stageBadge = '<span style="color:#95a5a6;font-weight:600;font-size:10px;">⛔ 衰退期</span>';
            else stageBadge = '<span style="color:#8888aa;font-size:10px;">' + stage + '</span>';
            
            html += '<tr style="background:rgba(52,152,219,0.08);">' +
                '<td colspan="5" style="padding:8px 10px;font-weight:600;font-size:13px;">' +
                '#' + theme.theme_rank + ' ' + themeName + ' ' + stageBadge +
                '<br><span style="font-weight:400;font-size:11px;color:var(--text-secondary);">' + coreDrivers + '</span>' +
                '</td></tr>';
            
            (theme.stocks || []).forEach(function(s) {
                html += '<tr>' +
                    '<td>' + s.rank + '</td>' +
                    '<td><span class="code-tag" onclick="openEastMoney(\'' + s.code + '\')">' + s.code + '</span></td>' +
                    '<td>' + s.name + '</td>' +
                    '<td>' + themeName + '</td>' +
                    '<td class="reason-cell">' + (s.reason || '-') + '</td>' +
                    '</tr>';
            });
        });
        tbody.innerHTML = html;
        if (pagEl) pagEl.innerHTML = '';
        return;
    }
    
    var page = _modelPages[model];
    var totalPages = Math.max(1, Math.ceil(stocks.length / MODEL_PAGE_SIZE));
    if (page > totalPages) { page = totalPages; _modelPages[model] = page; }
    var start = (page - 1) * MODEL_PAGE_SIZE;
    var end = Math.min(start + MODEL_PAGE_SIZE, stocks.length);
    var pageData = stocks.slice(start, end);

    var html = '';
    pageData.forEach(function(s) {
        html += '<tr>' +
            '<td>' + s.rank + '</td>' +
            '<td><span class="code-tag" onclick="openEastMoney(\'' + s.code + '\')">' + s.code + '</span></td>' +
            '<td>' + s.name + '</td>' +
            '<td>' + (s.sector || '-') + '</td>' +
            '<td class="reason-cell">' + (s.reason || '-') + '</td>' +
            '</tr>';
    });
    tbody.innerHTML = html;

    if (!pagEl) return;
    if (totalPages <= 1) {
        pagEl.innerHTML = '';
        return;
    }
    var ph = '<button onclick="modelGoPage(\'' + model + '\',' + (page - 1) + ')" ' + (page <= 1 ? 'disabled' : '') + '>\u25c0</button>';
    for (var i = 1; i <= totalPages; i++) {
        if (i === page) {
            ph += '<button class="active">' + i + '</button>';
        } else if (i === 1 || i === totalPages || Math.abs(i - page) <= 2) {
            ph += '<button onclick="modelGoPage(\'' + model + '\',' + i + ')">' + i + '</button>';
        } else if (Math.abs(i - page) === 3) {
            ph += '<button disabled>...</button>';
        }
    }
    ph += '<button onclick="modelGoPage(\'' + model + '\',' + (page + 1) + ')" ' + (page >= totalPages ? 'disabled' : '') + '>\u25b6</button>';
    ph += '<span class="page-info">' + page + '/' + totalPages + '</span>';
    pagEl.innerHTML = ph;
}

function modelGoPage(model, page) {
    var stocks = _modelData[model] || [];
    var totalPages = Math.max(1, Math.ceil(stocks.length / MODEL_PAGE_SIZE));
    if (page < 1 || page > totalPages) return;
    _modelPages[model] = page;
    renderModelTable(model, stocks);
}

async function loadModelTable(model) {
    var data = await api('/api/ai-stock-picks?source=' + model);
    if (!data || data.code !== 0) return;
    var stocks = data.data || [];
    var format = data.format || 'flat';
    _modelData[model] = stocks;
    if (!_modelPages[model]) _modelPages[model] = 1;
    renderModelTable(model, stocks, format);
}

async function startAIAnalysis() {
    var btn = $('btnAiAnalyze');
    btn.disabled = true;
    btn.innerHTML = '⏳ 分析中...';
    showToast('正在 AI 分析，请耐心等待...', 'info');
    var data = await api('/api/ai-analyze', { method: 'POST' });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        var info = data.data;
        $('count-deepseek').textContent = (info.deepseek_count || 0) + ' 只';
        $('count-kimi').textContent = (info.kimi_count || 0) + ' 只';
        $('count-gemini').textContent = (info.gemini_count || 0) + ' 只';
        $('count-grok').textContent = (info.grok_count || 0) + ' 只';
        $('count-chatgpt').textContent = (info.chatgpt_count || 0) + ' 只';
        loadModelTable('deepseek');
        loadModelTable('kimi');
        loadModelTable('gemini');
        loadModelTable('grok');
        loadModelTable('chatgpt');
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    } else {
        showToast('❌ AI 分析失败', 'error');
    }
    btn.disabled = false;
    btn.innerHTML = '🚀 开始 AI 分析';
}

function toggleImport(model) {
    var el = $('import-' + model);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function doImport(model) {
    var textarea = $('importText-' + model);
    var statusEl = $('importStatus-' + model);
    var jsonStr = textarea.value.trim();
    if (!jsonStr) {
        statusEl.textContent = '请输入 JSON 数据';
        statusEl.className = 'import-status err';
        return;
    }
    statusEl.textContent = '导入中...';
    statusEl.className = 'import-status';
    var data = await api('/api/ai-import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'model=' + encodeURIComponent(model) + '&json_data=' + encodeURIComponent(jsonStr)
    });
    if (data && data.code === 0) {
        statusEl.textContent = '✅ 导入成功，共 ' + (data.count || 0) + ' 只';
        statusEl.className = 'import-status ok';
        $('count-' + model).textContent = (data.count || 0) + ' 只';
        loadModelTable(model);
        textarea.value = '';
    } else if (data) {
        statusEl.textContent = '❌ ' + data.message;
        statusEl.className = 'import-status err';
    } else {
        statusEl.textContent = '❌ 导入失败';
        statusEl.className = 'import-status err';
    }
}

// ====== 提示词弹框 ======
function openPromptModal() {
    var modal = $('promptModal');
    modal.classList.add('show');
    loadPromptContent();
}

function closePromptModal() {
    $('promptModal').classList.remove('show');
}

async function loadPromptContent() {
    var statusEl = $('promptStatus');
    statusEl.textContent = '加载中...';
    var data = await api('/api/prompt-templates/active/content');
    if (data && data.code === 0 && data.data) {
        $('promptContent').value = data.data.content;
        statusEl.textContent = '当前版本: 最新版本';
    } else {
        showToast('❌ 加载提示词失败', 'error');
        statusEl.textContent = '加载失败';
    }
}

async function savePrompt() {
    var content = $('promptContent').value.trim();
    if (!content) {
        showToast('❌ 提示词内容不能为空', 'error');
        return;
    }
    var data = await api('/api/prompt-templates/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'name=' + encodeURIComponent('最新版本') + '&content=' + encodeURIComponent(content)
    });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        $('promptStatus').textContent = '已保存';
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

async function resetPromptToDefault() {
    if (!confirm('确定还原为默认版本吗？当前修改将丢失。')) return;
    var data = await api('/api/prompt-templates/reset-default', { method: 'POST' });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        loadPromptContent();
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

async function setPromptAsDefault() {
    if (!confirm('确定将当前版本设为默认版本吗？')) return;
    var data = await api('/api/prompt-templates/set-as-default', { method: 'POST' });
    if (data && data.code === 0) {
        showToast('✅ ' + data.message, 'success');
        $('promptStatus').textContent = '已设为默认';
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
    }
}

// 页面加载时自动从数据库恢复 AI 选股数据
(async function initAI() {
    var models = ['deepseek', 'kimi', 'gemini', 'grok', 'chatgpt'];
    for (var m of models) {
        var d = await api('/api/ai-stock-picks?source=' + m);
        if (d && d.code === 0 && d.data) {
            var fmt = d.format || 'flat';
            var countEl = $('count-' + m);
            if (countEl) countEl.textContent = d.data.length + ' 只';
            _modelData[m] = d.data;
            if (!_modelPages[m]) _modelPages[m] = 1;
            renderModelTable(m, d.data, fmt);
        }
    }
})();
