"""
数据库操作 - 连接管理、表结构、批量插入
"""
import sqlite3
from datetime import datetime
from typing import Optional

import pandas as pd

from .config import DB_PATH, SQL_BATCH_SIZE, logger


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table_schema():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
            price REAL, pct_chg REAL, turnover_rate REAL,
            volume_ratio REAL, sector TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    cursor.execute("PRAGMA table_info(market_snapshot)")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    for col_name, col_type in {
        "open": "REAL", "high": "REAL", "low": "REAL", "close": "REAL",
        "volume": "INTEGER", "amount": "REAL", "amplitude": "REAL", "change": "REAL",
        "circulate_mv": "REAL", "trade_datetime": "TEXT",
        "turnover_rate": "REAL", "volume_ratio": "REAL",
        "source": "TEXT DEFAULT 'tushare'",
    }.items():
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE market_snapshot ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass
    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_market_snapshot_unique
            ON market_snapshot(trade_date, code)
        """)
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def ensure_stock_cache_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_list_cache (
            code TEXT PRIMARY KEY, name TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
    conn.close()


def _save_cache(df: pd.DataFrame):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM stock_list_cache")
    for _, r in df.iterrows():
        cursor.execute("INSERT OR REPLACE INTO stock_list_cache (code, name) VALUES (?, ?)",
                       (r["code"], r["name"]))
    conn.commit()
    conn.close()


def _calc_circulate_mv(amount: float, turnover_rate: float) -> float:
    """根据成交额和换手率计算流通市值（元）
    流通市值 = 成交额 / (换手率/100)
    """
    if turnover_rate and turnover_rate > 0 and amount and amount > 0:
        return amount / (turnover_rate / 100)
    return 0.0


def _calc_amplitude(high: float, low: float, prev_close: float) -> float:
    """计算振幅（%）
    振幅 = (最高 - 最低) / 昨收 * 100
    """
    if prev_close and prev_close > 0:
        return round((high - low) / prev_close * 100, 2)
    return 0.0


def batch_insert(conn: sqlite3.Connection, df: pd.DataFrame, source: str = "tushare") -> int:
    """
    批量插入数据。
    
    参数：
        source: 数据来源，'tushare'（全量/增量）或 'realtime'（实时）
    
    行为：
    - tushare: INSERT OR REPLACE 覆盖整条记录，但会保留已有的 realtime 字段（turnover_rate, volume_ratio）
    - realtime: 
        * 如果当天已有 tushare 数据 → 只 UPDATE turnover_rate, volume_ratio，不改 source
        * 如果当天没有数据 → INSERT 并标记 source='realtime'
    """
    if df is None or df.empty:
        return 0
    cursor = conn.cursor()
    rows = 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if source == "tushare":
        # TuShare 覆盖：先查询已有的 realtime 数据，保留其字段
        existing_realtime = {}
        trade_dates = df["trade_date"].unique()
        for td in trade_dates:
            cursor.execute(
                "SELECT code, turnover_rate, volume_ratio FROM market_snapshot "
                "WHERE trade_date = ? AND source = 'realtime'",
                (td,)
            )
            for row in cursor.fetchall():
                existing_realtime[row["code"]] = {
                    "turnover_rate": row["turnover_rate"],
                    "volume_ratio": row["volume_ratio"],
                }
        
        for start in range(0, len(df), SQL_BATCH_SIZE):
            batch = df.iloc[start: start + SQL_BATCH_SIZE]
            values = []
            for _, r in batch.iterrows():
                amount = r.get("amount", 0) or 0
                turnover_rate = r.get("turnover_rate", 0) or 0
                volume_ratio = r.get("volume_ratio", 0) or 0
                circulate_mv = _calc_circulate_mv(amount, turnover_rate)
                
                # 保留实时的 turnover_rate 和 volume_ratio
                code = r["code"]
                if code in existing_realtime:
                    rt = existing_realtime[code]
                    if rt["turnover_rate"] is not None:
                        turnover_rate = rt["turnover_rate"]
                    if rt["volume_ratio"] is not None:
                        volume_ratio = rt["volume_ratio"]
                
                values.append((
                    r["trade_date"], r["code"], r["name"],
                    r.get("open"), r.get("close"), r.get("high"), r.get("low"),
                    r.get("volume"), amount, r.get("amplitude"),
                    r.get("pct_chg"), r.get("change"), turnover_rate,
                    volume_ratio, circulate_mv, now_str, source,
                ))
            cursor.executemany("""
                INSERT OR REPLACE INTO market_snapshot
                    (trade_date, code, name, open, close, high, low,
                     volume, amount, amplitude, pct_chg, change, turnover_rate,
                     volume_ratio, circulate_mv, trade_datetime, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, values)
            rows += len(values)
        conn.commit()
    
    elif source == "realtime":
        # 实时更新：
        # - 已有 tushare 记录 → 只 UPDATE turnover_rate, volume_ratio，不改 source
        # - 已有 realtime 记录 → UPDATE 所有字段，source 保持 realtime
        # - 没有记录 → INSERT 并标记 source='realtime'
        for start in range(0, len(df), SQL_BATCH_SIZE):
            batch = df.iloc[start: start + SQL_BATCH_SIZE]
            for _, r in batch.iterrows():
                trade_date = r["trade_date"]
                code = r["code"]
                
                cursor.execute(
                    "SELECT source FROM market_snapshot WHERE trade_date = ? AND code = ?",
                    (trade_date, code)
                )
                existing = cursor.fetchone()
                
                if existing and existing["source"] == "tushare":
                    # 已有 tushare 记录，只补充实时字段
                    cursor.execute("""
                        UPDATE market_snapshot SET
                            turnover_rate = COALESCE(?, turnover_rate),
                            volume_ratio = COALESCE(?, volume_ratio),
                            trade_datetime = ?
                        WHERE trade_date = ? AND code = ?
                    """, (
                        r.get("turnover_rate", None),
                        r.get("volume_ratio", None),
                        now_str, trade_date, code,
                    ))
                elif existing and existing["source"] == "realtime":
                    # 已有 realtime 记录，整条更新
                    cursor.execute("""
                        UPDATE market_snapshot SET
                            name = ?, open = ?, close = ?, high = ?, low = ?,
                            volume = ?, amount = ?, amplitude = ?,
                            pct_chg = ?, change = ?,
                            turnover_rate = ?, volume_ratio = ?,
                            trade_datetime = ?
                        WHERE trade_date = ? AND code = ?
                    """, (
                        r.get("name", ""),
                        r.get("open"), r.get("close"), r.get("high"), r.get("low"),
                        r.get("volume"), r.get("amount"), r.get("amplitude"),
                        r.get("pct_chg"), r.get("change"),
                        r.get("turnover_rate"), r.get("volume_ratio"),
                        now_str, trade_date, code,
                    ))
                else:
                    # 没有记录，插入并标记 realtime
                    cursor.execute("""
                        INSERT INTO market_snapshot
                            (trade_date, code, name, open, close, high, low,
                             volume, amount, amplitude, pct_chg, change,
                             turnover_rate, volume_ratio, trade_datetime, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade_date, code, r.get("name", ""),
                        r.get("open"), r.get("close"), r.get("high"), r.get("low"),
                        r.get("volume"), r.get("amount"), r.get("amplitude"),
                        r.get("pct_chg"), r.get("change"),
                        r.get("turnover_rate"), r.get("volume_ratio"),
                        now_str, "realtime",
                    ))
                rows += 1
        conn.commit()
    
    return rows
