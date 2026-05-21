"""
股票列表获取 - 多源容错 + 本地缓存兜底
"""
import pandas as pd

from .config import logger
from .db import get_connection, ensure_stock_cache_table, _save_cache


def _akshare_get_stock_list() -> pd.DataFrame:
    """通过 AKShare 获取 A 股股票列表"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            result = df[["代码", "名称"]].rename(columns={"代码": "code", "名称": "name"})
            result["code"] = result["code"].astype(str).str.strip()
            return result
    except Exception as e:
        logger.warning(f"AKShare 获取股票列表失败: {e}")
    return pd.DataFrame(columns=["code", "name"])


def _pytdx_get_stock_list() -> pd.DataFrame:
    """通过 Pytdx 获取 A 股股票列表"""
    try:
        from pytdx.hq import TDXParams
        from pytdx.hq import TdxHq_API
        from .config import PYTDX_IPS
        api = TdxHq_API()
        connected = False
        for ip, port in PYTDX_IPS:
            try:
                api.connect(ip, port)
                # Pytdx 没有 is_connected() 方法，用 client 属性判断
                if api.client is not None:
                    connected = True
                    break
            except Exception:
                continue
        if not connected:
            return pd.DataFrame(columns=["code", "name"])
        stocks = []
        for market in [TDXParams.MARKET_SZ, TDXParams.MARKET_SH]:
            data = api.get_security_list(market, 1, 5000)
            if data:
                for item in data:
                    code = item.get("code", "")
                    name = item.get("name", "")
                    if code and name:
                        stocks.append({"code": code, "name": name})
        api.disconnect()
        if stocks:
            return pd.DataFrame(stocks)
    except Exception as e:
        logger.warning(f"Pytdx 获取股票列表失败: {e}")
    return pd.DataFrame(columns=["code", "name"])


def _is_stock_code(code: str, name: str = "") -> bool:
    """判断是否为 A 股个股代码（过滤指数、债券等）"""
    if not code or len(code) != 6:
        return False
    if name:
        name_keywords = ["指数", "基金", "债券", "国债", "ETF", "LOF", "上证", "深证", "沪深"]
        for kw in name_keywords:
            if kw in name:
                return False
    if code.startswith("399"):
        return False
    if code.startswith("08") or code.startswith("09"):
        return False
    if code.startswith(("10", "11", "12")):
        return False
    if code.startswith(("688", "689")):
        return True
    if code.startswith(("600", "601", "602", "603", "604", "605", "606", "607", "608", "609")):
        return True
    if code.startswith(("000", "001", "002", "003")):
        return True
    if code.startswith(("300", "301", "302")):
        return True
    return False


def _baostock_get_stock_list() -> pd.DataFrame:
    """通过 BaoStock 获取 A 股股票列表"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            return pd.DataFrame(columns=["code", "name"])
        rs = bs.query_all_stock("2025-01-01")
        stocks = []
        while rs.next():
            s = rs.get_row_data()
            code = s[1] if len(s) > 1 else ""
            name = s[2] if len(s) > 2 else ""
            if code and name and _is_stock_code(code):
                stocks.append({"code": code, "name": name})
        bs.logout()
        if stocks:
            return pd.DataFrame(stocks)
    except Exception as e:
        logger.warning(f"BaoStock 获取股票列表失败: {e}")
    return pd.DataFrame(columns=["code", "name"])


def _tushare_get_stock_list() -> pd.DataFrame:
    """通过 TuShare Pro 获取 A 股股票列表"""
    try:
        import tushare as ts
        from config import TUSHARE_TOKEN
        pro = ts.pro_api(token=TUSHARE_TOKEN)
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
        if df is not None and not df.empty:
            result = df.rename(columns={"ts_code": "code", "name": "name"})
            result["code"] = result["code"].str.replace(r'\..*', '', regex=True)
            return result
    except Exception as e:
        logger.warning(f"TuShare 获取股票列表失败: {e}")
    return pd.DataFrame(columns=["code", "name"])


def get_stock_list() -> pd.DataFrame:
    """
    优先级：AKShare → Pytdx → BaoStock → TuShare → 本地缓存
    """
    ensure_stock_cache_table()
    fetchers = [
        ("AKShare", _akshare_get_stock_list),
        ("Pytdx", _pytdx_get_stock_list),
        ("BaoStock", _baostock_get_stock_list),
        ("TuShare", _tushare_get_stock_list),
    ]
    for name, fn in fetchers:
        logger.info(f"尝试通过 {name} 获取股票列表...")
        df = fn()
        if df is not None and not df.empty:
            _save_cache(df)
            logger.info(f"{name} 获取到 {len(df)} 只股票，已缓存")
            return df
        logger.warning(f"{name} 获取失败，尝试下一个...")

    logger.warning("所有在线数据源均失败，尝试本地缓存...")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, name FROM stock_list_cache ORDER BY code")
    rows = cursor.fetchall()
    conn.close()
    if rows:
        df = pd.DataFrame(rows, columns=["code", "name"])
        logger.info(f"从本地缓存读取股票列表: {len(df)} 只")
        return df
    logger.error("所有数据源（含本地缓存）均无法获取股票列表")
    return pd.DataFrame(columns=["code", "name"])
