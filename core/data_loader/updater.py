"""
更新调度 - 全量/增量/实时三种更新模式
"""
import time
import signal
import sys
from datetime import datetime, timedelta

from .config import logger, START_DATE, TODAY
from .db import get_connection, ensure_table_schema, ensure_stock_cache_table, batch_insert
from .history import get_trade_dates, fetch_by_trade_date
from .realtime import get_realtime_data
from .enrich import enrich_turnover_and_amplitude
from .validate import validate_data_integrity


update_status = {
    "running": False, "mode": "", "progress": "",
    "total": 0, "current": 0, "success": 0, "fail": 0,
    "rows": 0, "start_time": None, "elapsed": "",
    "logs": [],  # 每个交易日的写入记录
}
shutdown_flag = False


def signal_handler(sig, frame):
    global shutdown_flag
    if shutdown_flag:
        logger.warning("收到第二次中断信号，强制退出！")
        sys.exit(1)
    shutdown_flag = True
    logger.info("收到中断信号，正在等待当前任务完成后退出...")


# ============================================================
# 按交易日更新（全量/增量共用）
# ============================================================

def update_by_trade_dates(trade_dates: list, mode: str = "增量更新"):
    """
    按交易日列表逐个获取并写入数据库。
    全量/增量共用此函数，只是传入的交易日列表不同。
    """
    global update_status, shutdown_flag
    shutdown_flag = False
    update_status = {
        "running": True, "mode": mode,
        "progress": "初始化...", "total": len(trade_dates), "current": 0,
        "success": 0, "fail": 0, "rows": 0,
        "start_time": time.time(), "elapsed": "",
    }

    try:
        logger.info("=" * 60)
        logger.info(f"开始{mode}，共 {len(trade_dates)} 个交易日")
        logger.info("=" * 60)

        conn = get_connection()
        batch_count = 0
        logs = []

        for i, trade_date in enumerate(trade_dates):
            if shutdown_flag:
                logger.warning("收到中断信号，更新已暂停")
                update_status["progress"] = "已暂停"
                break

            update_status["current"] = i + 1
            update_status["progress"] = f"[{i+1}/{len(trade_dates)}] {trade_date}"

            # 频率控制：每 45 次等待 60 秒
            if batch_count >= 45:
                logger.info(f"TuShare 频率限制，等待 60 秒...（进度: {i}/{len(trade_dates)}）")
                time.sleep(60)
                batch_count = 0

            # 获取该交易日数据
            df = fetch_by_trade_date(trade_date)
            batch_count += 1

            if df is not None and not df.empty:
                rows = batch_insert(conn, df, source="tushare")
                update_status["success"] += 1
                update_status["rows"] += rows
                log_msg = f"✓ {trade_date} 写入 {rows} 条"
                logger.info(f"  {log_msg}")
                logs.append(log_msg)
            else:
                update_status["fail"] += 1
                log_msg = f"✗ {trade_date} 无数据"
                logger.warning(f"  {log_msg}")
                logs.append(log_msg)

            # 每处理一个交易日就更新日志列表
            update_status["logs"] = logs[-100:]  # 只保留最近 100 条

            if (i + 1) % 10 == 0:
                elapsed = time.time() - update_status["start_time"]
                logger.info(f"进度: {i+1}/{len(trade_dates)}, 成功: {update_status['success']}, "
                           f"失败: {update_status['fail']}, 写入: {update_status['rows']} 条, "
                           f"耗时: {elapsed:.0f}s")

        conn.close()

        elapsed = time.time() - update_status["start_time"]
        update_status["elapsed"] = f"{elapsed:.0f}s"
        logger.info(f"{mode}完成: 成功 {update_status['success']}/{len(trade_dates)}, "
                   f"写入 {update_status['rows']} 条, 耗时 {elapsed:.0f}s")
        update_status["progress"] = "完成"

    except Exception as e:
        logger.error(f"{mode}异常: {e}")
        update_status["progress"] = f"异常: {e}"
    finally:
        update_status["running"] = False


# ============================================================
# 全量更新
# ============================================================

def update_full():
    """
    全量更新：从 START_DATE 至今，全部重新下载。
    1. 清空旧数据
    2. 获取交易日历
    3. 按交易日逐个获取并写入
    """
    global update_status, shutdown_flag
    shutdown_flag = False
    update_status = {
        "running": True, "mode": "全量更新",
        "progress": "初始化...", "total": 0, "current": 0,
        "success": 0, "fail": 0, "rows": 0,
        "start_time": time.time(), "elapsed": "",
    }

    try:
        logger.info("=" * 60)
        logger.info("开始全量更新")
        logger.info("=" * 60)

        # 1. 清空旧数据
        update_status["progress"] = "清空旧数据..."
        logger.info("清空 market_snapshot 表...")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM market_snapshot")
        conn.commit()
        conn.close()
        logger.info("market_snapshot 表已清空")

        # 2. 获取交易日历
        update_status["progress"] = "获取交易日历..."
        trade_dates = get_trade_dates(START_DATE, TODAY)
        logger.info(f"共 {len(trade_dates)} 个交易日")

        # 3. 按交易日逐个获取并写入
        update_by_trade_dates(trade_dates, "全量更新")

    except Exception as e:
        logger.error(f"全量更新异常: {e}")
        update_status["progress"] = f"异常: {e}"
    finally:
        update_status["running"] = False


# ============================================================
# 增量更新
# ============================================================

def get_last_update_date() -> str:
    """获取数据库中最近一次 TuShare 更新的交易日（排除实时数据）"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(trade_date) FROM market_snapshot WHERE source = 'tushare'")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return START_DATE


def update_incremental():
    """
    增量更新：从上次更新的位置继续，只补缺失数据。
    1. 获取数据库中已有交易日
    2. 计算缺失的交易日
    3. 按缺失交易日逐个获取并写入
    """
    global update_status, shutdown_flag
    shutdown_flag = False
    update_status = {
        "running": True, "mode": "增量更新",
        "progress": "初始化...", "total": 0, "current": 0,
        "success": 0, "fail": 0, "rows": 0,
        "start_time": time.time(), "elapsed": "",
    }

    try:
        logger.info("=" * 60)
        logger.info("开始增量更新")
        logger.info("=" * 60)

        # 1. 获取交易日历
        update_status["progress"] = "获取交易日历..."
        all_dates = get_trade_dates(START_DATE, TODAY)
        logger.info(f"共 {len(all_dates)} 个交易日")

        # 2. 获取数据库中最大 TuShare 交易日
        last_date = get_last_update_date()
        logger.info(f"数据库中最近 TuShare 交易日: {last_date}")

        # 3. 计算需要更新的交易日
        # 只取最大交易日之后的（含当天，因为当天数据可能不全）
        missing_dates = [d for d in all_dates if d > last_date]
        # 最大交易日也加入重跑（可能上次跑到一半中断，数据不全）
        if last_date in all_dates:
            missing_dates.append(last_date)
            missing_dates = sorted(set(missing_dates))
            logger.info(f"最大交易日 {last_date} 加入重跑（防止数据不全）")
        logger.info(f"共 {len(missing_dates)} 个交易日需要更新")

        if not missing_dates:
            logger.info("没有缺失数据，增量更新完成")
            update_status["progress"] = "完成（无缺失数据）"
            update_status["running"] = False
            return

        # 4. 按缺失交易日逐个获取并写入
        update_by_trade_dates(missing_dates, "增量更新")

        # 5. 补充换手率和振幅
        if not shutdown_flag:
            update_status["progress"] = "补充换手率和振幅..."
            logger.info("开始补充换手率和振幅...")
            for date in missing_dates:
                enrich_turnover_and_amplitude(date)

        # 6. 数据完整性校验
        if not shutdown_flag:
            update_status["progress"] = "数据完整性校验..."
            logger.info("开始数据完整性校验...")
            for date in missing_dates:
                result = validate_data_integrity(date)
                for msg in result["messages"]:
                    logger.info(msg)

    except Exception as e:
        logger.error(f"增量更新异常: {e}")
        update_status["progress"] = f"异常: {e}"
    finally:
        update_status["running"] = False


# ============================================================
# 实时更新
# ============================================================

def update_realtime():
    """
    实时更新：只更新当天数据，批量查询。
    """
    global update_status, shutdown_flag
    shutdown_flag = False
    update_status = {
        "running": True, "mode": "实时更新",
        "progress": "初始化...", "total": 0, "current": 0,
        "success": 0, "fail": 0, "rows": 0,
        "start_time": time.time(), "elapsed": "",
    }

    try:
        logger.info("=" * 60)
        logger.info("开始实时更新")
        logger.info("=" * 60)

        # 1. 获取股票列表
        from .stock_list import get_stock_list
        update_status["progress"] = "获取股票列表..."
        stocks = get_stock_list()
        if stocks.empty:
            logger.error("无法获取股票列表，实时更新终止")
            update_status["progress"] = "失败：无法获取股票列表"
            update_status["running"] = False
            return

        codes = stocks["code"].tolist()
        total = len(codes)
        update_status["total"] = total
        logger.info(f"共 {total} 只股票需要更新")

        # 2. 批量获取实时行情
        update_status["progress"] = "获取实时行情..."
        df = get_realtime_data(codes)

        if df is None or df.empty:
            logger.error("获取实时行情失败")
            update_status["progress"] = "失败：获取实时行情失败"
            update_status["running"] = False
            return

        # 3. 写入数据库
        update_status["progress"] = "写入数据库..."
        conn = get_connection()
        rows = batch_insert(conn, df, source="realtime")
        conn.close()

        update_status["rows"] = rows
        update_status["success"] = len(df)
        logger.info(f"实时数据写入完成: {rows} 条")

        # 4. 补充换手率和振幅
        update_status["progress"] = "补充换手率和振幅..."
        enrich_turnover_and_amplitude(TODAY)

        # 5. 数据完整性校验
        update_status["progress"] = "数据完整性校验..."
        result = validate_data_integrity(TODAY)
        for msg in result["messages"]:
            logger.info(msg)

        elapsed = time.time() - update_status["start_time"]
        update_status["elapsed"] = f"{elapsed:.0f}s"
        logger.info(f"实时更新完成: {rows} 条, 耗时 {elapsed:.0f}s")
        update_status["progress"] = "完成"

    except Exception as e:
        logger.error(f"实时更新异常: {e}")
        update_status["progress"] = f"异常: {e}"
    finally:
        update_status["running"] = False


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    ensure_table_schema()
    ensure_stock_cache_table()

    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "incremental"

    if mode == "full":
        update_full()
    elif mode == "realtime":
        update_realtime()
    else:
        update_incremental()
