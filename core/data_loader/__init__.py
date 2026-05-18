"""
数据加载模块 - 批量下载 A 股历史行情数据并存入数据库

三种更新模式：
  1. 全量更新：从 20250101 至今，全部重新下载
  2. 增量更新：从上次更新的位置继续，只补缺失数据
  3. 实时更新：只更新当天数据，批量查询

数据源容错：
  - 全量/增量更新：Pytdx（主力，无频率限制）→ AKShare → TuShare → BaoStock
  - 实时更新：AKShare（东方财富）→ Pytdx（多IP切换）
  - 股票列表：AKShare → Pytdx → BaoStock → TuShare → 本地缓存
"""

from .db import (
    get_connection, ensure_table_schema, ensure_stock_cache_table,
    batch_insert, _save_cache, _calc_circulate_mv, _calc_amplitude,
)
from .stock_list import get_stock_list
from .history import get_trade_dates, fetch_by_trade_date
from .realtime import get_realtime_data
from .enrich import enrich_turnover_and_amplitude, enrich_all_history
from .validate import validate_data_integrity
from .updater import (
    update_full, update_incremental, update_realtime,
    get_last_update_date, update_status, shutdown_flag,
)

__all__ = [
    "get_connection", "ensure_table_schema", "ensure_stock_cache_table",
    "batch_insert", "get_stock_list",
    "get_trade_dates", "fetch_by_trade_date", "get_realtime_data",
    "enrich_turnover_and_amplitude", "validate_data_integrity",
    "update_full", "update_incremental", "update_realtime",
    "get_last_update_date", "update_status", "shutdown_flag",
]
