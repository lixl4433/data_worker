"""
实盘交易记录 API
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Form, Request

from web.config import get_conn, dict_from_row, logger

router = APIRouter(tags=["实盘交易"])


@router.post("/api/trade/create-batch")
async def api_trade_create_batch(request: Request):
    """创建新一批交易记录"""
    body = await request.json()
    stocks = body.get("stocks", [])
    if not stocks:
        return {"code": -1, "message": "股票列表为空，请先计算综合评分"}
    top10 = stocks[:10]

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(trade_date) FROM market_snapshot")
    latest_date = cursor.fetchone()[0]
    if not latest_date:
        conn.close()
        return {"code": -1, "message": "数据库无交易日数据"}

    cursor.execute("""
        SELECT trade_date FROM market_snapshot
        WHERE trade_date > ? GROUP BY trade_date ORDER BY trade_date LIMIT 1 OFFSET 2
    """, (latest_date,))
    sell_row = cursor.fetchone()
    sell_date = sell_row[0] if sell_row else ""

    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    buy_date = latest_date

    cursor.execute("""
        INSERT INTO trade_batches (batch_id, buy_date, sell_date, stock_count, status)
        VALUES (?, ?, ?, ?, 'holding')
    """, (batch_id, buy_date, sell_date, len(top10)))

    for s in top10:
        cursor.execute("""
            INSERT INTO trade_records (batch_id, trade_date, code, name, score, status)
            VALUES (?, ?, ?, ?, ?, 'holding')
        """, (batch_id, buy_date, s.get("code", ""), s.get("name", ""), s.get("score", 0)))

    conn.commit()
    conn.close()
    logger.info(f"创建交易批次: {batch_id}, {len(top10)} 只股票")

    return {
        "code": 0, "message": f"交易批次创建成功，共 {len(top10)} 只股票",
        "data": {"batch_id": batch_id, "buy_date": buy_date, "sell_date": sell_date, "stocks": top10},
    }


@router.get("/api/trade/batches")
async def api_trade_batches():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_batches ORDER BY created_at DESC")
    batches = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": batches}


@router.get("/api/trade/records")
async def api_trade_records(batch_id: str = ""):
    conn = get_conn()
    cursor = conn.cursor()
    if batch_id:
        cursor.execute("SELECT * FROM trade_records WHERE batch_id = ? ORDER BY id", (batch_id,))
    else:
        cursor.execute("SELECT * FROM trade_records ORDER BY created_at DESC")
    records = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": records}


@router.post("/api/trade/update-buy")
async def api_trade_update_buy(record_id: int = Form(...), buy_price: float = Form(...), shares: int = Form(0)):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE trade_records SET buy_price = ?, shares = ?, updated_at = datetime('now', 'localtime')
        WHERE id = ?
    """, (buy_price, shares, record_id))
    conn.commit()
    conn.close()
    return {"code": 0, "message": "更新成功"}


@router.post("/api/trade/settle")
async def api_trade_settle(batch_id: str = Form(...)):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_batches WHERE batch_id = ?", (batch_id,))
    batch = cursor.fetchone()
    if not batch:
        conn.close()
        return {"code": -1, "message": "批次不存在"}
    batch = dict(batch)
    sell_date = batch["sell_date"]

    cursor.execute("SELECT * FROM trade_records WHERE batch_id = ?", (batch_id,))
    records = [dict(row) for row in cursor.fetchall()]

    wins, losses, returns = 0, 0, []
    for r in records:
        if r["buy_price"] is None or r["buy_price"] == 0:
            continue
        cursor.execute("SELECT close FROM market_snapshot WHERE code = ? AND trade_date = ?", (r["code"], sell_date))
        sell_row = cursor.fetchone()
        if not sell_row:
            cursor.execute("SELECT close FROM market_snapshot WHERE code = ? ORDER BY trade_date DESC LIMIT 1", (r["code"],))
            sell_row = cursor.fetchone()
        if not sell_row:
            continue
        sell_price = sell_row[0]
        ret = round((sell_price - r["buy_price"]) / r["buy_price"] * 100, 2)
        if ret > 0:
            wins += 1
        else:
            losses += 1
        returns.append(ret)
        cursor.execute("""
            UPDATE trade_records SET sell_price = ?, return_pct = ?, status = 'settled', updated_at = datetime('now', 'localtime')
            WHERE id = ?
        """, (sell_price, ret, r["id"]))

    total = wins + losses
    avg_ret = round(sum(returns) / total, 2) if total > 0 else 0
    win_rate = round(wins / total * 100, 1) if total > 0 else 0
    cursor.execute("""
        UPDATE trade_batches SET win_count = ?, loss_count = ?, avg_return = ?, win_rate = ?, status = 'settled'
        WHERE batch_id = ?
    """, (wins, losses, avg_ret, win_rate, batch_id))
    conn.commit()
    conn.close()

    return {
        "code": 0, "message": "结算完成",
        "data": {"batch_id": batch_id, "total": total, "wins": wins, "losses": losses, "win_rate": win_rate, "avg_return": avg_ret},
    }


@router.get("/api/trade/stats")
async def api_trade_stats():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) as total_trades,
               SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN return_pct <= 0 THEN 1 ELSE 0 END) as losses,
               ROUND(AVG(return_pct), 2) as avg_return,
               COUNT(DISTINCT batch_id) as batch_count
        FROM trade_records WHERE status = 'settled' AND return_pct IS NOT NULL
    """)
    stats = dict(cursor.fetchone())
    total = stats["total_trades"] or 0
    wins = stats["wins"] or 0
    stats["win_rate"] = round(wins / total * 100, 1) if total > 0 else 0

    cursor.execute("""
        SELECT batch_id, buy_date, sell_date, stock_count, win_count, loss_count,
               avg_return, win_rate, status, created_at
        FROM trade_batches WHERE status = 'settled' ORDER BY created_at DESC
    """)
    batches = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": {"overall": stats, "batches": batches}}
