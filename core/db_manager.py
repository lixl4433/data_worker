"""
数据库管理模块 - 初始化和管理 SQLite 数据库
"""

import sqlite3
from pathlib import Path

# 使用 config 中的路径配置（自动适配 Windows / Linux）
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> Path:
    """
    初始化数据库，创建三张核心表并建立索引。

    表结构：
    1. market_snapshot  - 全市场快照表
    2. hot_events       - 热点事件表
    3. signals          - 选股信号表
    """
    # 确保 data 目录存在
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    # ============================================================
    # 1. market_snapshot - 全市场快照表
    # ============================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_snapshot (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date  TEXT    NOT NULL,   -- 日期，格式：YYYYMMDD
            code        TEXT    NOT NULL,   -- 股票代码，如：000001
            name        TEXT    NOT NULL,   -- 股票名称
            price       REAL,               -- 现价
            pct_chg     REAL,               -- 涨跌幅（%）
            turnover_rate REAL,              -- 换手率（%）
            volume_ratio REAL,              -- 量比
            sector      TEXT,               -- 所属行业
            created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # ============================================================
    # 2. hot_events - 热点事件表
    # ============================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hot_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_date  TEXT    NOT NULL,   -- 事件日期，格式：YYYYMMDD
            keyword     TEXT    NOT NULL,   -- 关键词，如：SpaceX
            content     TEXT,               -- 消息摘要
            impact_level TEXT,              -- 影响等级：高/中/低
            created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # ============================================================
    # 3. signals - 选股信号表
    # ============================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date  TEXT    NOT NULL,   -- 交易日期，格式：YYYYMMDD
            code        TEXT    NOT NULL,   -- 股票代码
            name        TEXT    NOT NULL,   -- 股票名称
            tech_score  REAL,               -- 技术分
            event_score REAL,               -- 事件分
            reason      TEXT,               -- 推荐理由
            created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # ============================================================
    # 索引优化 - 确保 5000 只股票下查询依然飞快
    # ============================================================

    # market_snapshot 索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_snapshot_code
        ON market_snapshot (code)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_snapshot_trade_date
        ON market_snapshot (trade_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_market_snapshot_code_date
        ON market_snapshot (code, trade_date)
    """)

    # hot_events 索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hot_events_keyword
        ON hot_events (keyword)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hot_events_event_date
        ON hot_events (event_date)
    """)

    # signals 索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_code
        ON signals (code)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_trade_date
        ON signals (trade_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_signals_code_date
        ON signals (code, trade_date)
    """)

    conn.commit()
    conn.close()

    return DB_PATH


if __name__ == "__main__":
    db_path = init_db()
    print(f"数据库初始化成功")
    print(f"文件存放路径: {db_path}")
