// ====== 热点新闻页面（按日期持久化） ======
var _currentHotNewsDateKey = '';

async function loadHotNewsDates() {
    var data = await api('/api/hot-news/dates');
    if (!data || data.code !== 0) return;
    var dates = data.data || [];
    var sel = $('hotNewsDateSelect');
    sel.innerHTML = '';
    dates.forEach(function(d) {
        var opt = document.createElement('option');
        opt.value = d.date_key;
        opt.textContent = d.date_key + ' (' + (d.total_count || 0) + '条)';
        sel.appendChild(opt);
    });
    if (dates.length > 0) {
        sel.value = _currentHotNewsDateKey || dates[0].date_key;
    }
}

async function switchHotNewsDate() {
    var sel = $('hotNewsDateSelect');
    var dateKey = sel.value;
    if (!dateKey) return;
    _currentHotNewsDateKey = dateKey;
    
    var data = await api('/api/hot-news/load?date_key=' + encodeURIComponent(dateKey));
    if (data && data.code === 0 && data.data) {
        var content = data.data.text || '暂无数据';
        $('hotNewsContent').textContent = content;
        $('hotNewsContent').style.display = 'block';
        $('hotNewsStatus').textContent = '共 ' + (data.data.total_count || 0) + ' 条热点，更新时间: ' + (data.data.timestamp || '-');
    } else {
        $('hotNewsContent').style.display = 'none';
        $('hotNewsStatus').textContent = '该日期无热点新闻数据';
    }
}

async function loadHotNews() {
    var btn = $('btnHotNews');
    btn.disabled = true;
    btn.innerHTML = '⏳ 采集中...';
    $('hotNewsStatus').textContent = '正在采集各平台热点新闻...';
    $('hotNewsContent').style.display = 'none';
    
    var data = await api('/api/hot-news');
    if (data && data.code === 0) {
        var content = data.data.text || '暂无数据';
        _currentHotNewsDateKey = data.data.date_key || '';
        $('hotNewsContent').textContent = content;
        $('hotNewsContent').style.display = 'block';
        $('hotNewsStatus').textContent = '共 ' + (data.data.total_count || 0) + ' 条热点，更新时间: ' + (data.data.timestamp || '-');
        
        // 刷新日期列表
        await loadHotNewsDates();
        var sel = $('hotNewsDateSelect');
        if (sel && _currentHotNewsDateKey) sel.value = _currentHotNewsDateKey;
    } else if (data) {
        showToast('❌ ' + data.message, 'error');
        $('hotNewsStatus').textContent = '❌ ' + data.message;
    } else {
        showToast('❌ 热点新闻采集失败', 'error');
        $('hotNewsStatus').textContent = '❌ 采集失败';
    }
    btn.disabled = false;
    btn.innerHTML = '🔄 刷新热点新闻';
}

// 页面加载时自动恢复最新热点新闻
(async function initHotNews() {
    // 加载日期列表
    await loadHotNewsDates();
    
    // 加载最新热点新闻
    var data = await api('/api/hot-news/load');
    if (data && data.code === 0 && data.data) {
        var content = data.data.text || '暂无数据';
        _currentHotNewsDateKey = data.data.date_key || '';
        $('hotNewsContent').textContent = content;
        $('hotNewsContent').style.display = 'block';
        $('hotNewsStatus').textContent = '共 ' + (data.data.total_count || 0) + ' 条热点，更新时间: ' + (data.data.timestamp || '-');
        
        // 同步日期选择器
        var sel = $('hotNewsDateSelect');
        if (sel && _currentHotNewsDateKey) sel.value = _currentHotNewsDateKey;
    }
})();
