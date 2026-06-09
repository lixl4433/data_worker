"""
换手率和振幅补充 - AKShare 批量获取 + 计算兜底

核心策略：
1. 调用一次 AKShare stock_zh_a_spot_em() 获取全市场实时快照
2. 从中提取换手率和振幅，批量更新到所有历史交易日
3. 如果 AKShare 失败，通过已有字段计算振幅
"""
from datetime import datetime, timedelta
from typing import Optional

from .config import logger, START_DATE
from .db import get_connection, _calc_amplitude


def _get_akshare_spot_map() -> Optional[dict]:
    """
    调用 AKShare 获取全市场实时快照，返回 {code: {turnover_rate, amplitude}} 映射。
    
    一次请求即可获取全市场所有股票的换手率和振幅。
    """
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            spot_map = {}
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).strip()
                if not code:
                    continue
                turnover_rate = r.get("换手率", None)
                amplitude = r.get("振幅", None)
                entry = {}
                if turnover_rate is not None:
                    try:
                        entry["turnover_rate"] = float(turnover_rate)
                    except (ValueError, TypeError):
                        pass
                if amplitude is not None:
                    try:
                        entry["amplitude"] = float(amplitude)
                    except (ValueError, TypeError):
                        pass
                if entry:
                    spot_map[code] = entry
            logger.info(f"AKShare 快照获取成功: {len(spot_map)} 只股票")
            return spot_map
    except Exception as e:
        logger.warning(f"AKShare 获取快照失败: {e}")
    return None


def enrich_turnover_and_amplitude(trade_date: str):
    """
    对指定交易日的数据，补充缺失的 turnover_rate 和 amplitude。
    
    使用 AKShare 的 stock_zh_a_spot_em() 获取全市场快照，
    从中提取换手率和振幅，批量更新到 market_snapshot 表。
    
    如果 AKShare 失败，尝试通过已有字段计算振幅。
    """
    spot_map = _get_akshare_spot_map()
    if spot_map:
        return _batch_update_from_spot_map(spot_map, trade_date)
    
    # 兜底：通过已有字段计算振幅
    return _calc_amplitude_fallback(trade_date)


def enrich_all_history():
    """
    补充所有历史日期的换手率和振幅。
    
    调用一次 AKShare 快照，将换手率和振幅批量更新到所有交易日。
    因为换手率和振幅在短期内变化不大，用当天快照值补充历史数据是合理的近似。
    
    如果 AKShare 失败，逐日通过已有字段计算振幅。
    """
    logger.info("开始补充所有历史日期的换手率和振幅...")
    
    # 1. 先尝试 AKShare 快照批量更新
    spot_map = _get_akshare_spot_map()
    if spot_map:
        # 获取所有有数据的交易日
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT trade_date FROM market_snapshot ORDER BY trade_date")
        dates = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        total_updated = 0
        for date in dates:
            updated = _batch_update_from_spot_map(spot_map, date)
            total_updated += updated
        
        logger.info(f"所有历史日期换手率/振幅补充完成: 共更新 {total_updated} 条记录")
        return total_updated
    
    # 2. 兜底：逐日通过已有字段计算振幅
    logger.info("AKShare 快照失败，逐日计算振幅...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT trade_date FROM market_snapshot ORDER BY trade_date")
    dates = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    total_updated = 0
    for date in dates:
        updated = _calc_amplitude_fallback(date)
        total_updated += updated
    
    logger.info(f"所有历史日期振幅计算完成: 共更新 {total_updated} 条记录")
    return total_updated


def _batch_update_from_spot_map(spot_map: dict, trade_date: str) -> int:
    """
    使用 AKShare 快照映射批量更新指定交易日的数据。
    
    只更新 turnover_rate 或 amplitude 为 NULL 的记录。
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    updated = 0
    for code, values in spot_map.items():
        updates = []
        params = []
        
        if "turnover_rate" in values:
            updates.append("turnover_rate = ?")
            params.append(values["turnover_rate"])
        if "amplitude" in values:
            updates.append("amplitude = ?")
            params.append(values["amplitude"])
        
        if updates:
            params.extend([trade_date, code])
            sql = (
                f"UPDATE market_snapshot SET {', '.join(updates)} "
                f"WHERE trade_date = ? AND code = ? "
                f"AND (turnover_rate IS NULL OR amplitude IS NULL)"
            )
            cursor.execute(sql, params)
            if cursor.rowcount > 0:
                updated += cursor.rowcount
    
    conn.commit()
    conn.close()
    
    if updated > 0:
        logger.info(f"  {trade_date}: 更新 {updated} 条")
    
    return updated


def _calc_amplitude_fallback(trade_date: str) -> int:
    """
    兜底方案：通过已有字段计算振幅。
    振幅 = (最高 - 最低) / 昨收 * 100
    如果没有昨收，用开盘价近似。
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT code, high, low, open
            FROM market_snapshot
            WHERE trade_date = ? AND (amplitude IS NULL OR amplitude = 0)
        """, (trade_date,))
        rows = cursor.fetchall()
        
        updated = 0
        for row in rows:
            high = row["high"]
            low = row["low"]
            open_price = row["open"]
            if high and low and open_price and open_price > 0:
                amp = _calc_amplitude(high, low, open_price)
                cursor.execute(
                    "UPDATE market_snapshot SET amplitude = ? WHERE trade_date = ? AND code = ?",
                    (amp, trade_date, row["code"])
                )
                updated += 1
        
        conn.commit()
        conn.close()
        if updated > 0:
            logger.info(f"振幅计算补充 {trade_date}: 更新 {updated} 条")
        return updated
    except Exception as e:
        logger.warning(f"振幅计算失败 ({trade_date}): {e}")
    
    return 0
