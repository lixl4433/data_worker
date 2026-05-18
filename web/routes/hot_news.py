"""
热点新闻 API（按日期持久化）
"""
import json
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter

from web.config import get_conn, logger
from core.hot_news import collect_all_hot_news, analyze_hot_news_with_deepseek

router = APIRouter(tags=["热点新闻"])


def save_hot_news_to_db(date_key: str, content: str, total_count: int, timestamp: str):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO hot_news (date_key, content, total_count, timestamp)
            VALUES (?, ?, ?, ?)
        """, (date_key, content, total_count, timestamp))
        conn.commit()
        conn.close()
        logger.info(f"热点新闻已保存: date_key={date_key}")
    except Exception as e:
        logger.error(f"保存热点新闻失败: {e}")


def load_hot_news_from_db(date_key: str) -> dict:
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT content, total_count, timestamp FROM hot_news WHERE date_key = ?", (date_key,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"text": row["content"], "total_count": row["total_count"], "timestamp": row["timestamp"]}
        return None
    except Exception as e:
        logger.error(f"加载热点新闻失败: {e}")
        return None


@router.get("/api/hot-news")
async def api_hot_news():
    """采集各平台热点新闻，自动保存到数据库（每天只保留最后一次）"""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, collect_all_hot_news)

        lines = []
        for source_name, items in result["sources"].items():
            lines.append(f"【{source_name}】")
            for i, item in enumerate(items[:10], 1):
                title = item.get("title", "")
                hot = f" (热度: {item['hot_value']})" if item.get("hot_value") else ""
                lines.append(f"  {i}. {title}{hot}")
            lines.append("")
        raw_text = "\n".join(lines)

        def _analyze():
            return analyze_hot_news_with_deepseek(raw_text)

        aggregated = await loop.run_in_executor(None, _analyze)
        final_text = aggregated if aggregated else raw_text

        date_key = datetime.now().strftime("%Y-%m-%d")
        save_hot_news_to_db(date_key, final_text, result["total_count"], result["timestamp"])

        return {
            "code": 0,
            "data": {
                "text": final_text,
                "total_count": result["total_count"],
                "timestamp": result["timestamp"],
                "date_key": date_key,
            },
        }
    except Exception as e:
        logger.error(f"热点新闻采集异常: {e}")
        return {"code": -1, "message": f"热点新闻采集失败: {str(e)}"}


@router.get("/api/hot-news/dates")
async def api_hot_news_dates():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT date_key, total_count, timestamp, created_at FROM hot_news ORDER BY date_key DESC")
    dates = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": dates}


@router.get("/api/hot-news/load")
async def api_hot_news_load(date_key: str = ""):
    if not date_key:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT date_key FROM hot_news ORDER BY date_key DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return {"code": 0, "data": None, "date_key": ""}
        date_key = row["date_key"]
    data = load_hot_news_from_db(date_key)
    if data:
        data["date_key"] = date_key
        return {"code": 0, "data": data, "date_key": date_key}
    return {"code": 0, "data": None, "date_key": date_key}
