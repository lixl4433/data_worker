# 量化选股系统

基于 **FastAPI** 的 **A 股量化选股系统**，集成多 AI 模型选股 + 多因子量化评分 + 技术面分析 + 买卖点建议。

## 📁 项目结构

```
data_worker/
├── main.py                  # FastAPI 主入口，端口 7654
├── config.py                # 核心配置（数据库路径、TuShare Token、Pytdx 配置）
├── requirements.txt         # Python 依赖
├── download_data.bat        # 数据下载脚本
├── start_web.bat            # 启动脚本
│
├── core/                    # 核心业务逻辑
│   ├── data_loader/         # 数据加载模块（多数据源容错）
│   │   ├── config.py        #   数据加载配置
│   │   ├── db.py            #   数据库操作
│   │   ├── stock_list.py    #   股票列表获取（AKShare → Pytdx → BaoStock → TuShare）
│   │   ├── history.py       #   历史行情下载（TuShare）
│   │   ├── realtime.py      #   实时行情获取（AKShare → Pytdx）
│   │   ├── enrich.py        #   数据增强（换手率、振幅计算）
│   │   ├── validate.py      #   数据完整性校验
│   │   └── updater.py       #   定时更新调度
│   ├── ai_analyzer.py       # AI 分析（5 模型选股 + 多因子评分 + 买卖点建议）
│   ├── db_manager.py        # 数据库初始化
│   ├── longhu.py            # 龙虎榜数据采集（东方财富 API + DeepSeek 回退）
│   └── hot_news.py          # 热点新闻采集（抖音/微博/东方财富/同花顺/华尔街见闻）
│
├── web/                     # Web 服务层
│   ├── config.py            # Web 配置（日志、数据库连接）
│   ├── routes/              # API 路由
│   │   ├── data_update.py   #   数据更新 + 强势股票计算
│   │   ├── ai_analysis.py   #   AI 5 模型选股（DeepSeek/Kimi/Gemini/Grok/ChatGPT）
│   │   ├── score_board.py   #   综合评分持久化
│   │   ├── hot_news.py      #   热点新闻
│   │   ├── longhu.py        #   龙虎榜
│   │   ├── trade_records.py #   实盘交易记录
│   │   ├── wx_push.py       #   微信推送（PushPlus）
│   │   ├── prompts.py       #   提示词管理
│   │   └── status.py        #   系统状态
│   ├── static/              # 前端静态文件
│   │   ├── css/style.css    #   样式
│   │   └── js/              #   JavaScript
│   │       ├── app.js       #   全局工具函数
│   │       └── pages/       #   各页面 JS
│   └── templates/           # Jinja2 模板
│       ├── layout.html      #   布局模板
│       └── pages/           #   各页面模板
│
├── data/                    # SQLite 数据库
│   └── quant_storage.db
└── scripts/
    ├── _check_ai.py         # AI 检查脚本
    └── _test_pytdx.py       # Pytdx 连接测试
```

## 🔑 核心功能

### 1. 数据采集
多数据源容错（AKShare → Pytdx → BaoStock → TuShare），支持全量/增量/实时三种更新模式，自动定时调度。

### 2. AI 选股
调用 5 个大模型 API 进行题材分析：
- **DeepSeek** / **Kimi** / **Gemini** / **Grok** / **ChatGPT**
- 支持手动导入 Gemini/Grok/ChatGPT 结果
- 被多个模型同时推荐的股票获得 AI 热度加分

### 3. 多因子评分
6 大技术面因子 + 动态权重 + 加分项：

| 因子 | 含义 | 评分范围 |
|------|------|----------|
| 趋势 | 近5日涨幅+上涨天数 | 0~25 |
| 量价 | 量比配合涨幅 | -15~20 |
| RSI | RSI底背离/顶背离 | -15~20 |
| 稳定 | 上涨稳定性 | -8~15 |
| 突破 | 靠近高点+放量 | 0~10 |
| 箱体 | 箱体底部放量 | 0~10 |

**加分项**：龙虎榜净买入、机构参与、AI 热度（多模型推荐）

**动态权重**：根据大盘状态（多头/空头）和策略类型（突破型/埋伏型）自动调整

### 4. 技术面分析
- 支撑位/压力位（箱体 + 近期高低点）
- 买入价/卖出价/止损价建议
- RSI 背离检测
- 策略分类（突破型 A / 埋伏型 B / 观望型 C）

### 5. 龙虎榜
东方财富 API 优先，DeepSeek 联网搜索回退。

### 6. 热点新闻
采集 5 个平台热搜（抖音/微博/东方财富/同花顺/华尔街见闻），DeepSeek 聚合分析。

### 7. 实盘交易
批次管理、买入/结算、胜率统计。

### 8. 微信推送
通过 PushPlus 推送选股结果。

## 🛠 技术栈

- **后端**：Python + FastAPI + SQLite
- **前端**：原生 JS + CSS（无框架）
- **AI**：DeepSeek / Kimi / Gemini / Grok / ChatGPT（OpenAI 兼容 API）
- **数据**：AKShare / TuShare / Pytdx

## 🚀 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置 API Key
编辑 `config.py`，填入以下配置：
- `DEEPSEEK_API_KEY` - DeepSeek API Key
- `KIMI_API_KEY` - Kimi API Key
- `GEMINI_API_KEY` - Google Gemini API Key
- `TUSHARE_TOKEN` - TuShare Token（用于获取历史行情）
- `PUSHPLUS_TOKEN` - PushPlus Token（可选，用于微信推送）

### 3. 下载数据
```bash
python main.py
```
或双击 `start_web.bat` 启动。

### 4. 访问系统
打开浏览器访问 `http://localhost:7654`

## 📊 页面说明

| 页面 | 路由 | 功能 |
|------|------|------|
| 数据更新 | `/data-update` | 手动/自动更新行情数据 |
| AI 分析 | `/ai-analysis` | 运行 AI 选股，查看各模型推荐 |
| 综合评分 | `/score-board` | 多因子评分排行榜，买卖点建议 |
| 热点新闻 | `/hot-news` | 多平台热搜，AI 聚合分析 |
| 龙虎榜 | `/longhu` | 龙虎榜数据查看 |
| 交易记录 | `/trade-records` | 实盘交易管理 |
