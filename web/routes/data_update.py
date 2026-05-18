"""
数据更新 API + 强势股票计算
"""
import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter

from web.config import get_conn, dict_from_row, logger
from core.data_loader import (
    update_status as data_update_status,
    update_full, update_incremental, update_realtime,
)


router = APIRouter(tags=["数据更新"])


def compute_strong_stocks(top_n: int = 50) -> list:
    """
    多因子选股模型，含风险过滤：
    1. 排除 ST/*ST/退市股
    2. 排除股价 < 2 元或 > 200 元的股票
    3. 排除近5日涨幅过大（> 50%）的短期过热股
    4. 排除处于历史高位（近1年价格百分位 > 80%）的股票
    5. 多因子评分：涨幅(35%) + 振幅(15%) + 量比(25%) + 位置评分(25%)
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(trade_date) FROM market_snapshot")
    latest_date = cursor.fetchone()[0]
    if not latest_date:
        conn.close()
        return []

    latest_dt = datetime.strptime(latest_date, "%Y%m%d")
    date_5 = (latest_dt - timedelta(days=10)).strftime("%Y%m%d")
    date_20 = (latest_dt - timedelta(days=30)).strftime("%Y%m%d")
    date_250 = (latest_dt - timedelta(days=365)).strftime("%Y%m%d")

    sql = """
        WITH
        stock_stats AS (
            SELECT
                code, name,
                AVG(pct_chg) AS avg_pct_5d,
                AVG(amplitude) AS avg_amp_5d,
                AVG(volume) AS avg_vol_5d,
                (SELECT close FROM market_snapshot sub
                 WHERE sub.code = ms.code AND sub.trade_date = ?) AS latest_close
            FROM market_snapshot ms
            WHERE trade_date >= ? AND trade_date <= ?
            GROUP BY code
            HAVING COUNT(*) >= 3
        ),
        stock_vol_20 AS (
            SELECT code, AVG(volume) AS avg_vol_20d
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
            GROUP BY code
            HAVING COUNT(*) >= 10
        ),
        stock_price_range AS (
            SELECT
                code,
                MIN(low) AS year_low,
                MAX(high) AS year_high
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
            GROUP BY code
            HAVING COUNT(*) >= 60
        )
        SELECT
            s.code, s.name,
            ROUND(s.avg_pct_5d, 2) AS avg_pct_5d,
            ROUND(s.avg_amp_5d, 2) AS avg_amp_5d,
            ROUND(CAST(s.avg_vol_5d AS REAL) / NULLIF(v.avg_vol_20d, 0), 2) AS vol_ratio,
            ROUND(s.latest_close, 2) AS latest_close,
            ROUND(pr.year_low, 2) AS year_low,
            ROUND(pr.year_high, 2) AS year_high,
            ROUND(
                CASE
                    WHEN pr.year_high = pr.year_low THEN 50
                    ELSE (s.latest_close - pr.year_low) / (pr.year_high - pr.year_low) * 100
                END
            , 2) AS price_percentile,
            ROUND(
                s.avg_pct_5d * 0.35
                + s.avg_amp_5d * 0.15
                + (CAST(s.avg_vol_5d AS REAL) / NULLIF(v.avg_vol_20d, 0)) * 10 * 0.25
                + CASE
                    WHEN (s.latest_close - pr.year_low) / NULLIF(pr.year_high - pr.year_low, 0) BETWEEN 0.2 AND 0.6 THEN 15
                    WHEN (s.latest_close - pr.year_low) / NULLIF(pr.year_high - pr.year_low, 0) < 0.2 THEN 5
                    WHEN (s.latest_close - pr.year_low) / NULLIF(pr.year_high - pr.year_low, 0) BETWEEN 0.6 AND 0.8 THEN 0
                    ELSE -20
                END * 0.25
            , 2) AS score
        FROM stock_stats s
        LEFT JOIN stock_vol_20 v ON s.code = v.code
        LEFT JOIN stock_price_range pr ON s.code = pr.code
        WHERE 1=1
            AND s.name NOT LIKE '%ST%'
            AND s.name NOT LIKE '%退%'
            AND (s.latest_close >= 2.0 AND s.latest_close <= 200.0)
            AND s.avg_pct_5d <= 50.0
            AND (s.latest_close - pr.year_low) / NULLIF(pr.year_high - pr.year_low, 0) <= 0.8
            AND v.avg_vol_20d > 0
        ORDER BY score DESC
        LIMIT ?
    """

    cursor.execute(sql, (
        latest_date, date_5, latest_date,
        date_20, latest_date,
        date_250, latest_date,
        top_n,
    ))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for i, row in enumerate(rows, 1):
        d = dict_from_row(row)
        d["rank"] = i
        result.append(d)
    return result


@router.get("/api/strong-stocks")
async def api_strong_stocks(top_n: int = 50):
    stocks = compute_strong_stocks(top_n)
    return {"code": 0, "data": stocks, "total": len(stocks)}


@router.get("/api/db-overview")
async def api_db_overview():
    """数据库概览：交易日数、总记录数、日期范围"""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT trade_date) AS days,
                COUNT(*) AS rows,
                MIN(trade_date) AS start_date,
                MAX(trade_date) AS end_date,
                MAX(created_at) AS last_update
            FROM market_snapshot
            WHERE source = 'tushare'
        """)
        row = cursor.fetchone()
        conn.close()
        return {"code": 0, "data": dict_from_row(row)}
    except Exception as e:
        logger.error(f"获取数据库概览失败: {e}")
        return {"code": -1, "message": str(e)}


@router.get("/api/update-status")
async def api_update_status():
    return {"code": 0, "data": dict(data_update_status)}


@router.post("/api/update-full")
async def api_update_full():
    if data_update_status["running"]:
        return {"code": -1, "message": "已有更新任务正在运行"}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, update_full)
    return {"code": 0, "message": "全量更新完成"}


@router.post("/api/update-incremental")
async def api_update_incremental():
    if data_update_status["running"]:
        return {"code": -1, "message": "已有更新任务正在运行"}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, update_incremental)
    return {"code": 0, "message": "增量更新完成"}


@router.post("/api/update-realtime")
async def api_update_realtime():
    if data_update_status["running"]:
        return {"code": -1, "message": "已有更新任务正在运行"}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, update_realtime)
    return {"code": 0, "message": "实时更新完成"}


@router.post("/api/recompute-strong")
async def api_recompute_strong():
    """重新计算强势股票，并将结果推送到微信"""
    try:
        stocks = compute_strong_stocks(50)
        count = len(stocks)
        from web.routes.wx_push import send_wx_push, format_stocks_for_push
        title = f"强势股票 TOP {count} - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        content = format_stocks_for_push(stocks, "🔥 强势股票 TOP 50")
        push_ok = await send_wx_push(title, content)
        return {
            "code": 0,
            "message": f"强势股票计算完成，共 {count} 只" + ("，已推送微信" if push_ok else "，微信推送失败"),
            "count": count,
            "push_ok": push_ok,
        }
    except Exception as e:
        logger.error(f"重新结算强势股票异常: {e}")
        return {"code": -1, "message": f"计算异常: {str(e)}"}
