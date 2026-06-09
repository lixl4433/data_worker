"""
实时数据获取 - AKShare → Pytdx 多源容错
"""
from typing import Optional, List

import pandas as pd

from .config import logger, get_today, PYTDX_IPS


def _akshare_get_realtime(codes: List[str]) -> Optional[pd.DataFrame]:
    """通过 AKShare 获取实时行情"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            df_filtered = df[df["代码"].isin(codes)].copy()
            if df_filtered.empty:
                return None
            result = pd.DataFrame()
            result["trade_date"] = get_today()
            result["code"] = df_filtered["代码"].astype(str).str.strip()
            result["name"] = df_filtered["名称"]
            result["open"] = pd.to_numeric(df_filtered.get("今开", 0), errors="coerce")
            result["close"] = pd.to_numeric(df_filtered.get("最新价", 0), errors="coerce")
            result["high"] = pd.to_numeric(df_filtered.get("最高", 0), errors="coerce")
            result["low"] = pd.to_numeric(df_filtered.get("最低", 0), errors="coerce")
            result["volume"] = pd.to_numeric(df_filtered.get("成交量", 0), errors="coerce")
            result["amount"] = pd.to_numeric(df_filtered.get("成交额", 0), errors="coerce")
            result["amplitude"] = pd.to_numeric(df_filtered.get("振幅", 0), errors="coerce")
            result["pct_chg"] = pd.to_numeric(df_filtered.get("涨跌幅", 0), errors="coerce")
            result["change"] = pd.to_numeric(df_filtered.get("涨跌额", 0), errors="coerce")
            result["turnover_rate"] = pd.to_numeric(df_filtered.get("换手率", 0), errors="coerce")
            result["volume_ratio"] = pd.to_numeric(df_filtered.get("量比", 0), errors="coerce")
            result["source"] = "realtime"
            return result
    except Exception as e:
        logger.warning(f"AKShare 获取实时数据失败: {e}")
    return None


def _pytdx_get_realtime(codes: List[str]) -> Optional[pd.DataFrame]:
    """通过 Pytdx 获取实时行情"""
    try:
        from pytdx.hq import TdxHq_API
        api = TdxHq_API()
        connected = False
        for ip, port in PYTDX_IPS:
            try:
                api.connect(ip, port, time_out=3)
                if api.client is not None:
                    connected = True
                    logger.info(f"Pytdx 连接成功: {ip}:{port}")
                    break
            except Exception:
                continue
        if not connected:
            logger.warning("Pytdx 无法连接，跳过实时数据获取")
            return None
        
        # 按市场分组
        sz_codes = [c for c in codes if not c.startswith(("6", "9"))]
        sh_codes = [c for c in codes if c.startswith(("6", "9"))]
        
        records = []
        
        # 获取深圳市场实时行情
        if sz_codes:
            for i in range(0, len(sz_codes), 100):
                batch = sz_codes[i:i+100]
                data = api.get_security_quotes(0, batch)
                if data:
                    for item in data:
                        records.append({
                            "trade_date": get_today(),
                            "code": str(item.get("code", "")),
                            "name": str(item.get("name", "")),
                            "open": float(item.get("open", 0)),
                            "close": float(item.get("price", 0)),
                            "high": float(item.get("high", 0)),
                            "low": float(item.get("low", 0)),
                            "volume": int(item.get("vol", 0)),
                            "amount": float(item.get("amount", 0)),
                            "amplitude": None,
                            "pct_chg": float(item.get("rise_and_fall", 0)),
                            "change": float(item.get("rise_and_fall", 0)),
                            "turnover_rate": None,
                        })
        
        # 获取上海市场实时行情
        if sh_codes:
            for i in range(0, len(sh_codes), 100):
                batch = sh_codes[i:i+100]
                data = api.get_security_quotes(1, batch)
                if data:
                    for item in data:
                        records.append({
                            "trade_date": get_today(),
                            "code": str(item.get("code", "")),
                            "name": str(item.get("name", "")),
                            "open": float(item.get("open", 0)),
                            "close": float(item.get("price", 0)),
                            "high": float(item.get("high", 0)),
                            "low": float(item.get("low", 0)),
                            "volume": int(item.get("vol", 0)),
                            "amount": float(item.get("amount", 0)),
                            "amplitude": None,
                            "pct_chg": float(item.get("rise_and_fall", 0)),
                            "change": float(item.get("rise_and_fall", 0)),
                            "turnover_rate": None,
                        })
        
        api.disconnect()
        
        if records:
            result = pd.DataFrame(records)
            logger.info(f"Pytdx 获取实时数据成功: {len(result)} 条")
            return result
        
    except Exception as e:
        logger.warning(f"Pytdx 获取实时数据失败: {e}")
        try:
            api.disconnect()
        except Exception:
            pass
    return None


def get_realtime_data(codes: List[str]) -> Optional[pd.DataFrame]:
    """
    获取实时行情数据。
    
    优先级：
    1. AKShare（东方财富，字段最全含换手率/振幅）
    2. Pytdx（回退，无频率限制）
    """
    # 1. AKShare（主力）
    df = _akshare_get_realtime(codes)
    if df is not None and not df.empty:
        return df
    
    # 2. Pytdx（回退）
    logger.info("AKShare 获取实时数据失败，尝试 Pytdx...")
    df = _pytdx_get_realtime(codes)
    if df is not None and not df.empty:
        return df
    
    logger.error("所有数据源均无法获取实时数据")
    return None
