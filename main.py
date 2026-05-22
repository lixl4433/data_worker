"""
选股系统 - FastAPI 后台服务（主入口）

按功能拆分到 web/routes/ 目录：
  - data_update.py  数据更新 + 强势股票计算
  - ai_analysis.py  AI 5 模型选股
  - score_board.py  综合评分持久化
  - hot_news.py     热点新闻
  - trade_records.py 实盘交易记录
  - wx_push.py      微信推送
  - longhu.py       龙虎榜
  - prompts.py      提示词管理
  - status.py       系统状态
"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from web.config import get_conn, TEMPLATES_DIR, STATIC_DIR, logger
from web.routes.ai_analysis import load_ai_picks_from_db


# ---------------------------------------------------------------------------
# 数据库初始化（建表）
# ---------------------------------------------------------------------------
def init_database():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            tech_score REAL, event_score REAL, reason TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wx_push (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wx_id TEXT NOT NULL UNIQUE, remark TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            sector TEXT DEFAULT '', reason TEXT DEFAULT '', rank INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(model, code)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL, trade_date TEXT NOT NULL,
            code TEXT NOT NULL, name TEXT NOT NULL, score REAL,
            buy_price REAL, shares INTEGER DEFAULT 0,
            sell_price REAL, return_pct REAL,
            status TEXT DEFAULT 'holding',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_batches (
            batch_id TEXT PRIMARY KEY,
            buy_date TEXT NOT NULL, sell_date TEXT NOT NULL,
            stock_count INTEGER DEFAULT 0, win_count INTEGER DEFAULT 0,
            loss_count INTEGER DEFAULT 0, avg_return REAL, win_rate REAL,
            status TEXT DEFAULT 'holding',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hot_news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_key TEXT NOT NULL, content TEXT NOT NULL,
            total_count INTEGER DEFAULT 0, timestamp TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(date_key)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS score_board (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_key TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            sector TEXT DEFAULT '', reason TEXT DEFAULT '',
            score REAL, total_score REAL, avg_pct_5d REAL, vol_ratio REAL,
            latest_close REAL, rsi_divergence INTEGER DEFAULT 0,
            strategy_type TEXT DEFAULT '',
            support_1 REAL, support_2 REAL, resistance_1 REAL, resistance_2 REAL,
            buy_price REAL, sell_price REAL, stop_loss REAL,
            sources TEXT DEFAULT '', rank INTEGER DEFAULT 0,
            score_detail TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(date_key, code)
        )
    """)
    # 兼容旧表：如果 score_detail 列不存在则添加
    try:
        cursor.execute("ALTER TABLE score_board ADD COLUMN score_detail TEXT DEFAULT ''")
    except Exception:
        pass  # 列已存在
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prompt_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE, content TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    # 检查是否有默认提示词
    cursor.execute("SELECT COUNT(*) FROM prompt_templates")
    if cursor.fetchone()[0] == 0:
        from core.ai_analyzer import PROMPT_TEMPLATE
        cursor.execute(
            "INSERT INTO prompt_templates (name, content, is_default) VALUES (?, ?, 1)",
            ("默认版本", PROMPT_TEMPLATE)
        )
        cursor.execute(
            "INSERT INTO prompt_templates (name, content, is_default) VALUES (?, ?, 0)",
            ("最新版本", PROMPT_TEMPLATE)
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    load_ai_picks_from_db()
    logger.info("服务启动完成")
    yield
    logger.info("服务关闭")
    
app = FastAPI(title="量化选股系统", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    return templates.TemplateResponse(request, "pages/data_update.html", {"request": request, "active_tab": "data"})

@app.get("/ai-analysis", response_class=HTMLResponse)
async def ai_analysis_page(request: Request):
    return templates.TemplateResponse(request, "pages/ai_analysis.html", {"request": request, "active_tab": "ai"})

@app.get("/trade-records", response_class=HTMLResponse)
async def trade_records_page(request: Request):
    return templates.TemplateResponse(request, "pages/trade_records.html", {"request": request, "active_tab": "trade"})

@app.get("/wx-push", response_class=HTMLResponse)
async def wx_push_page(request: Request):
    return templates.TemplateResponse(request, "pages/wx_push.html", {"request": request, "active_tab": "wx"})

@app.get("/hot-news", response_class=HTMLResponse)
async def hot_news_page(request: Request):
    return templates.TemplateResponse(request, "pages/hot_news.html", {"request": request, "active_tab": "news"})

@app.get("/score-board", response_class=HTMLResponse)
async def score_board_page(request: Request):
    return templates.TemplateResponse(request, "pages/score_board.html", {"request": request, "active_tab": "score"})

@app.get("/longhu", response_class=HTMLResponse)
async def longhu_page(request: Request):
    return templates.TemplateResponse(request, "pages/longhu.html", {"request": request, "active_tab": "longhu"})

@app.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request):
    return templates.TemplateResponse(request, "pages/prompts.html", {"request": request, "active_tab": "prompts"})


# ---------------------------------------------------------------------------
# 注册 API 路由
# ---------------------------------------------------------------------------
from web.routes.data_update import router as data_update_router
from web.routes.ai_analysis import router as ai_analysis_router
from web.routes.score_board import router as score_board_router
from web.routes.hot_news import router as hot_news_router
from web.routes.trade_records import router as trade_records_router
from web.routes.wx_push import router as wx_push_router
from web.routes.longhu import router as longhu_router
from web.routes.prompts import router as prompts_router
from web.routes.status import router as status_router
from web.routes.backtest import router as backtest_router

app.include_router(data_update_router)
app.include_router(ai_analysis_router)
app.include_router(score_board_router)
app.include_router(hot_news_router)
app.include_router(trade_records_router)
app.include_router(wx_push_router)
app.include_router(longhu_router)
app.include_router(prompts_router)
app.include_router(status_router)
app.include_router(backtest_router)


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7654)
