"""
综合评分 API（按日期持久化）
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Request

from web.config import get_conn, logger

router = APIRouter(tags=["综合评分"])


def save_score_board_to_db(date_key: str, stocks: list):
    if not stocks:
        return
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM score_board WHERE date_key = ?", (date_key,))
        for s in stocks:
            sources_str = ""
            if s.get("sources") and isinstance(s["sources"], list):
                # 去重并保留顺序
                seen = set()
                unique_sources = []
                for src in s["sources"]:
                    if src not in seen:
                        seen.add(src)
                        unique_sources.append(src)
                sources_str = ",".join(unique_sources)
            cursor.execute("""
                INSERT OR REPLACE INTO score_board 
                (date_key, code, name, sector, reason, score, total_score, avg_pct_5d, vol_ratio,
                 latest_close, rsi_divergence, strategy_type, support_1, support_2,
                 resistance_1, resistance_2, buy_price, sell_price, stop_loss, sources, rank,
                 score_detail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_key, s.get("code", ""), s.get("name", ""), s.get("sector", ""),
                s.get("reason", ""), s.get("score"), s.get("total_score"),
                s.get("avg_pct_5d"), s.get("vol_ratio"), s.get("latest_close"),
                s.get("rsi_divergence", 0), s.get("strategy_type", ""),
                s.get("support_1"), s.get("support_2"),
                s.get("resistance_1"), s.get("resistance_2"),
                s.get("buy_price"), s.get("sell_price"), s.get("stop_loss"),
                sources_str, s.get("rank", 0),
                s.get("score_detail", "")
            ))
        conn.commit()
        logger.info(f"综合评分已保存: date_key={date_key}, count={len(stocks)}")
    except Exception as e:
        logger.error(f"保存综合评分失败: {e}")
    finally:
        conn.close()


def load_score_board_from_db(date_key: str) -> list:
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM score_board WHERE date_key = ? ORDER BY rank", (date_key,))
        rows = cursor.fetchall()
        conn.close()
        stocks = []
        for row in rows:
            d = dict(row)
            if d.get("sources"):
                d["sources"] = d["sources"].split(",")
            else:
                d["sources"] = []
            stocks.append(d)
        return stocks
    except Exception as e:
        logger.error(f"加载综合评分失败: {e}")
        return []


@router.get("/api/score-board/dates")
async def api_score_board_dates():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date_key, COUNT(*) as count, MAX(created_at) as created_at
        FROM score_board GROUP BY date_key ORDER BY date_key DESC
    """)
    dates = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": dates}


@router.get("/api/score-board/load")
async def api_score_board_load(date_key: str = ""):
    if not date_key:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT date_key FROM score_board GROUP BY date_key ORDER BY date_key DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {"code": 0, "data": [], "date_key": ""}
        date_key = row["date_key"]
    stocks = load_score_board_from_db(date_key)
    return {"code": 0, "data": stocks, "date_key": date_key}


@router.post("/api/score-board/save")
async def api_score_board_save(request: Request):
    body = await request.json()
    stocks = body.get("stocks", [])
    if not stocks:
        return {"code": -1, "message": "股票列表为空"}
    date_key = datetime.now().strftime("%Y-%m-%d")
    save_score_board_to_db(date_key, stocks)
    return {"code": 0, "message": f"已保存到 {date_key}", "date_key": date_key}
