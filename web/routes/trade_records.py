"""
实盘交易记录 API — 用于用户真实交易记录和分析

功能：
  - 从评分系统导入推荐股票（预填策略类型、止损止盈）
  - 手动录入任意交易
  - 平仓记录（卖出价、费用、持有天数）
  - 多维度统计（按策略、按月、按是否遵守系统）
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Request

from web.config import get_conn, logger

router = APIRouter(tags=["实盘交易"])


# ================================================================
# 创建交易（从评分导入或手动）
# ================================================================
@router.post("/api/trade/create")
async def api_trade_create(request: Request):
    """创建一条实盘交易记录"""
    body = await request.json()
    required = ["code", "name", "buy_price", "shares", "entry_date"]
    for f in required:
        if f not in body:
            return {"code": -1, "message": f"缺少必填字段: {f}"}

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO trade_records
        (batch_id, trade_date, code, name, sector, strategy_type, score, buy_price, shares, entry_date,
         stop_loss, take_profit, hold_days_recommended,
         source, followed_system, note, status, created_at)
        VALUES ('', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'holding', datetime('now','localtime'))
    """, (
        body["code"], body["name"], body.get("sector", ""),
        body.get("strategy_type", ""), body.get("score"),
        body["buy_price"], body["shares"], body["entry_date"],
        body.get("stop_loss"), body.get("take_profit"),
        body.get("hold_days_recommended", 5),
        body.get("source", "manual"),
        body.get("followed_system", 1),
        body.get("note", ""),
    ))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    logger.info(f"创建交易记录: {body['code']} {body['name']} 买入={body['buy_price']}")
    return {"code": 0, "message": "交易记录已创建", "data": {"id": trade_id}}


# ================================================================
# 批量导入（从评分结果导入 TOP N）
# ================================================================
@router.post("/api/trade/import-from-scored")
async def api_trade_import_from_scored(request: Request):
    """从综合评分结果批量导入交易记录"""
    body = await request.json()
    stocks = body.get("stocks", [])
    entry_date = body.get("entry_date", datetime.now().strftime("%Y-%m-%d"))
    if not stocks:
        return {"code": -1, "message": "股票列表为空"}

    conn = get_conn()
    cursor = conn.cursor()
    ids = []
    for s in stocks:
        cursor.execute("""
            INSERT INTO trade_records
            (batch_id, trade_date, code, name, sector, strategy_type, score, buy_price, shares, entry_date,
             stop_loss, take_profit, hold_days_recommended,
             source, followed_system, status, created_at)
            VALUES ('', '', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ai_scored', 1, 'holding', datetime('now','localtime'))
        """, (
            s.get("code", ""), s.get("name", ""), s.get("sector", ""),
            s.get("strategy_type", ""), s.get("score"),
            s.get("buy_price"), s.get("shares", 0), entry_date,
            s.get("stop_loss"), s.get("take_profit"),
            s.get("hold_days_recommended", 5),
        ))
        ids.append(cursor.lastrowid)
    conn.commit()
    conn.close()
    return {"code": 0, "message": f"已导入 {len(ids)} 条交易记录", "data": {"ids": ids}}


# ================================================================
# 平仓
# ================================================================
@router.post("/api/trade/close")
async def api_trade_close(request: Request):
    """平仓：记录卖出价、卖出日期、费用"""
    body = await request.json()
    trade_id = body.get("id")
    if not trade_id:
        return {"code": -1, "message": "缺少交易ID"}

    sell_price = body.get("sell_price")
    exit_date = body.get("exit_date", datetime.now().strftime("%Y-%m-%d"))
    fees = body.get("fees", 0)

    if not sell_price:
        return {"code": -1, "message": "缺少卖出价"}

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_records WHERE id = ?", (trade_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"code": -1, "message": "交易记录不存在"}
    trade = dict(row)

    buy_price = trade["buy_price"]
    if not buy_price or buy_price == 0:
        conn.close()
        return {"code": -1, "message": "买入价为空，无法计算收益"}

    # 计算收益
    return_pct = round((sell_price - buy_price) / buy_price * 100, 2)
    net_return_pct = round(((sell_price - buy_price) * trade["shares"] - fees)
                            / (buy_price * trade["shares"]) * 100, 2)

    # 计算实际持有天数
    entry_date = trade.get("entry_date")
    holding_days = None
    if entry_date and exit_date:
        try:
            ed = datetime.strptime(entry_date, "%Y-%m-%d")
            xd = datetime.strptime(exit_date, "%Y-%m-%d")
            holding_days = (xd - ed).days
        except:
            pass

    cursor.execute("""
        UPDATE trade_records SET
            sell_price = ?, exit_date = ?, fees = ?,
            return_pct = ?, net_return_pct = ?, holding_days_actual = ?,
            status = 'closed', updated_at = datetime('now','localtime')
        WHERE id = ?
    """, (sell_price, exit_date, fees, return_pct, net_return_pct, holding_days, trade_id))
    conn.commit()
    conn.close()

    return {
        "code": 0, "message": "平仓成功",
        "data": {"return_pct": return_pct, "net_return_pct": net_return_pct, "holding_days": holding_days},
    }


# ================================================================
# 查询
# ================================================================
@router.get("/api/trade/list")
async def api_trade_list(status: str = "", strategy_type: str = "", source: str = ""):
    """查询交易记录列表，支持按状态/策略/来源过滤"""
    conn = get_conn()
    cursor = conn.cursor()
    conditions = []
    params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if strategy_type:
        conditions.append("strategy_type = ?")
        params.append(strategy_type)
    if source:
        conditions.append("source = ?")
        params.append(source)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    cursor.execute(f"SELECT * FROM trade_records {where} ORDER BY created_at DESC", params)
    records = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": records}


@router.get("/api/trade/detail")
async def api_trade_detail(id: int):
    """查询单条交易详情"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_records WHERE id = ?", (id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"code": -1, "message": "记录不存在"}
    return {"code": 0, "data": dict(row)}


# ================================================================
# 更新
# ================================================================
@router.post("/api/trade/update")
async def api_trade_update(request: Request):
    """更新交易记录（如修改买入价、备注等）"""
    body = await request.json()
    trade_id = body.get("id")
    if not trade_id:
        return {"code": -1, "message": "缺少交易ID"}

    allowed = ["buy_price", "shares", "entry_date", "stop_loss", "take_profit",
               "hold_days_recommended", "followed_system", "note", "strategy_type", "sector"]
    updates = []
    params = []
    for k in allowed:
        if k in body:
            updates.append(f"{k} = ?")
            params.append(body[k])

    if not updates:
        return {"code": -1, "message": "没有需要更新的字段"}

    updates.append("updated_at = datetime('now','localtime')")
    params.append(trade_id)

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE trade_records SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return {"code": 0, "message": "已更新"}


# ================================================================
# 删除
# ================================================================
@router.post("/api/trade/delete")
async def api_trade_delete(request: Request):
    """删除交易记录"""
    body = await request.json()
    trade_id = body.get("id")
    if not trade_id:
        return {"code": -1, "message": "缺少交易ID"}
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trade_records WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()
    return {"code": 0, "message": "已删除"}


# ================================================================
# 统计
# ================================================================
@router.get("/api/trade/stats")
async def api_trade_stats():
    """多维度统计"""
    conn = get_conn()
    cursor = conn.cursor()

    def wr(rows):
        """从查询结果计算胜率统计"""
        total = len(rows)
        if total == 0:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                    "avg_return": 0, "net_avg_return": 0, "cum_return": 0}
        wins = sum(1 for r in rows if r > 0)
        losses = total - wins
        return {
            "total": total, "wins": wins, "losses": losses,
            "win_rate": round(wins / total * 100, 1),
            "avg_return": round(sum(rows) / total, 2),
        }

    # 整体统计
    cursor.execute("SELECT return_pct FROM trade_records WHERE status = 'closed' AND return_pct IS NOT NULL")
    all_rets = [r[0] for r in cursor.fetchall()]

    overall = wr(all_rets)
    if all_rets:
        overall["cum_return"] = round(sum(all_rets), 2)
        overall["net_avg_return"] = round(
            sum(abs(r) for r in all_rets) / len(all_rets), 2
        )

    # 按策略统计
    cursor.execute("""
        SELECT strategy_type, return_pct FROM trade_records
        WHERE status = 'closed' AND return_pct IS NOT NULL AND strategy_type != ''
    """)
    by_strategy = {}
    for st, ret in cursor.fetchall():
        if st not in by_strategy:
            by_strategy[st] = []
        by_strategy[st].append(ret)
    strategy_stats = {k: wr(v) for k, v in by_strategy.items()}

    # 按是否遵守系统统计
    cursor.execute("""
        SELECT followed_system, return_pct FROM trade_records
        WHERE status = 'closed' AND return_pct IS NOT NULL
    """)
    by_follow = {}
    for f, ret in cursor.fetchall():
        key = "followed" if f == 1 else "discretionary"
        if key not in by_follow:
            by_follow[key] = []
        by_follow[key].append(ret)
    follow_stats = {k: wr(v) for k, v in by_follow.items()}

    # 月度统计
    cursor.execute("""
        SELECT substr(entry_date, 1, 7) as month, return_pct FROM trade_records
        WHERE status = 'closed' AND return_pct IS NOT NULL AND entry_date IS NOT NULL
        ORDER BY month
    """)
    by_month = {}
    for m, ret in cursor.fetchall():
        if m not in by_month:
            by_month[m] = []
        by_month[m].append(ret)
    month_stats = {k: wr(v) for k, v in by_month.items()}

    # 持仓和总览
    cursor.execute("SELECT COUNT(*) FROM trade_records WHERE status = 'holding'")
    holding = cursor.fetchone()[0]

    conn.close()

    return {
        "code": 0, "data": {
            "overall": overall,
            "by_strategy": strategy_stats,
            "by_follow": follow_stats,
            "by_month": month_stats,
            "holding_count": holding,
        }
    }


# ================================================================
# 向后兼容：保留旧的 batch 接口
# ================================================================
@router.get("/api/trade/batches")
async def api_trade_batches():
    """保留的旧批次接口（返回空）"""
    return {"code": 0, "data": []}

@router.post("/api/trade/create-batch")
async def api_trade_create_batch():
    return {"code": -1, "message": "已废弃，请使用 /api/trade/create 单条录入"}

@router.post("/api/trade/update-buy")
async def api_trade_update_buy():
    return {"code": -1, "message": "已废弃，请使用 /api/trade/update"}

@router.post("/api/trade/settle")
async def api_trade_settle():
    return {"code": -1, "message": "已废弃，请使用 /api/trade/close 逐条平仓"}
