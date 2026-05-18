"""
系统状态 API
"""
from datetime import datetime

from fastapi import APIRouter

from web.config import get_conn

router = APIRouter(tags=["系统状态"])


@router.get("/api/status")
async def api_status():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT code) FROM market_snapshot")
    stock_count = cursor.fetchone()[0]
    cursor.execute("SELECT MAX(trade_date) FROM market_snapshot")
    latest_date = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM wx_push")
    wx_count = cursor.fetchone()[0]
    cursor.execute("""
        SELECT trade_date, COUNT(*) as cnt
        FROM market_snapshot GROUP BY trade_date ORDER BY trade_date DESC LIMIT 10
    """)
    daily_counts = {row["trade_date"]: row["cnt"] for row in cursor.fetchall()}
    cursor.execute("SELECT COUNT(*) FROM market_snapshot")
    total_records = cursor.fetchone()[0]
    conn.close()
    return {
        "code": 0,
        "data": {
            "stock_count": stock_count,
            "latest_date": latest_date,
            "total_records": total_records,
            "daily_counts": daily_counts,
            "wx_push_count": wx_count,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
