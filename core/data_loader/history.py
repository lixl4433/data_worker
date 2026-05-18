"""
历史数据下载 - 仅使用 TuShare Pro（按交易日获取）
"""
from datetime import datetime, timedelta
from typing import Optional, List

import pandas as pd

from .config import logger


def get_trade_dates(start: str, end: str) -> List[str]:
    """获取交易日历"""
    import tushare as ts
    pro = ts.pro_api()
    try:
        cal = pro.trade_cal(start_date=start, end_date=end)
        trade_dates = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
        return trade_dates
    except Exception:
        # 如果获取失败，生成所有工作日
        trade_dates = []
        start_dt = datetime.strptime(start, "%Y%m%d")
        end_dt = datetime.strptime(end, "%Y%m%d")
        d = start_dt
        while d <= end_dt:
            if d.weekday() < 5:
                trade_dates.append(d.strftime("%Y%m%d"))
            d += timedelta(days=1)
        return trade_dates


def _get_stock_name_map() -> dict:
    """从本地缓存获取 code -> name 映射"""
    from .db import get_connection
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name FROM stock_list_cache")
        return {row[0]: row[1] for row in cursor.fetchall()}
    except Exception:
        return {}
    finally:
        conn.close()


def fetch_by_trade_date(trade_date: str) -> Optional[pd.DataFrame]:
    """
    获取指定交易日所有股票的数据。
    返回 DataFrame，列：trade_date, code, name, open, close, high, low, volume, amount, pct_chg, change
    """
    import time
    import tushare as ts
    pro = ts.pro_api()

    try:
        df = pro.daily(trade_date=trade_date)
        if df is None or df.empty:
            return None

        # 获取股票名称映射
        name_map = _get_stock_name_map()

        records = []
        for _, row in df.iterrows():
            ts_code = row.get("ts_code", "")
            code = ts_code.split(".")[0] if ts_code else ""
            if not code:
                continue
            records.append({
                "trade_date": str(row.get("trade_date", "")),
                "code": code,
                "name": name_map.get(code, ""),
                "open": float(row.get("open", 0)),
                "close": float(row.get("close", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "volume": int(row.get("vol", 0)),
                "amount": float(row.get("amount", 0)),
                "pct_chg": float(row.get("pct_chg", 0)),
                "change": float(row.get("change", 0)),
                "source": "tushare",
            })

        result = pd.DataFrame(records)
        return result

    except Exception as e:
        logger.warning(f"获取交易日 {trade_date} 失败: {e}")
        return None
