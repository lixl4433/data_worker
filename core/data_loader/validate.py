"""
数据完整性校验
"""
from .config import logger
from .db import get_connection


def validate_data_integrity(trade_date: str) -> dict:
    """
    校验指定交易日的数据完整性。
    
    Returns:
        dict: {
            "ok": True/False,
            "stock_count": int,
            "duplicates": int,
            "null_fields": {field_name: count},
            "messages": [str, ...],
        }
    """
    result = {
        "ok": True,
        "stock_count": 0,
        "duplicates": 0,
        "null_fields": {},
        "messages": [],
    }
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # 1. 检查股票数量
        cursor.execute(
            "SELECT COUNT(*) FROM market_snapshot WHERE trade_date = ?",
            (trade_date,)
        )
        stock_count = cursor.fetchone()[0]
        result["stock_count"] = stock_count
        
        if stock_count == 0:
            result["ok"] = False
            result["messages"].append(f"交易日 {trade_date} 无数据")
            conn.close()
            return result
        
        if stock_count < 1000:
            result["messages"].append(f"⚠️ 股票数量偏少: {stock_count} 只（正常应在 4000+）")
        
        # 2. 检查重复记录
        cursor.execute("""
            SELECT COUNT(*) FROM (
                SELECT trade_date, code, COUNT(*) as cnt
                FROM market_snapshot
                WHERE trade_date = ?
                GROUP BY trade_date, code
                HAVING cnt > 1
            )
        """, (trade_date,))
        duplicates = cursor.fetchone()[0]
        result["duplicates"] = duplicates
        if duplicates > 0:
            result["ok"] = False
            result["messages"].append(f"❌ 发现 {duplicates} 条重复记录")
        
        # 3. 检查关键字段空值
        key_fields = ["open", "close", "high", "low", "volume", "amount", "pct_chg"]
        for field in key_fields:
            cursor.execute(
                f"SELECT COUNT(*) FROM market_snapshot WHERE trade_date = ? AND ({field} IS NULL OR {field} = 0)",
                (trade_date,)
            )
            null_count = cursor.fetchone()[0]
            if null_count > 0:
                result["null_fields"][field] = null_count
                if null_count > stock_count * 0.5:
                    result["messages"].append(f"⚠️ {field} 缺失严重: {null_count}/{stock_count}")
        
        # 4. 检查换手率和振幅
        for field in ["turnover_rate", "amplitude"]:
            cursor.execute(
                f"SELECT COUNT(*) FROM market_snapshot WHERE trade_date = ? AND ({field} IS NULL OR {field} = 0)",
                (trade_date,)
            )
            null_count = cursor.fetchone()[0]
            if null_count > 0:
                result["null_fields"][field] = null_count
        
        conn.close()
        
        if result["ok"]:
            result["messages"].append(f"✅ 数据完整性校验通过: {stock_count} 只股票")
        
        return result
        
    except Exception as e:
        result["ok"] = False
        result["messages"].append(f"❌ 校验异常: {e}")
        return result
