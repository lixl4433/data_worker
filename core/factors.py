"""
因子定义和计算模块 — 全向量化实现

核心计算全部使用 groupby().rolling() C 级运算，避免 Python 逐组循环。
5000 只股票 × 300 天 ≈ 150 万行，应在 10-30 秒内完成。
"""
import numpy as np
import pandas as pd

FACTOR_COLS = [
    "f_mom_1d", "f_mom_5d", "f_mom_10d", "f_mom_20d", "f_mom_60d",
    "f_vs_ma5", "f_vs_ma10", "f_vs_ma20", "f_vs_ma60", "f_ma5_ma20",
    "f_vol_ratio", "f_vol_5d", "f_vol_10d", "f_turnover", "f_turnover_5d",
    "f_atr", "f_amplitude", "f_volatility_10d", "f_volatility_20d",
    "f_rsi_14", "f_macd", "f_bollinger", "f_k", "f_d",
    "f_position_20d", "f_position_60d", "f_high_distance",
    "f_vpt_5d",
]

FACTOR_DESC = {
    "f_mom_1d": "1日收益率", "f_mom_5d": "5日累计收益",
    "f_mom_10d": "10日累计收益", "f_mom_20d": "20日累计收益",
    "f_mom_60d": "60日累计收益",
    "f_vs_ma5": "偏离5日均线", "f_vs_ma10": "偏离10日均线",
    "f_vs_ma20": "偏离20日均线", "f_vs_ma60": "偏离60日均线",
    "f_ma5_ma20": "5日与20日均线差",
    "f_vol_ratio": "量比(当日量/20日均量)",
    "f_vol_5d": "5日成交量变化率", "f_vol_10d": "10日成交量变化率",
    "f_turnover": "换手率", "f_turnover_5d": "换手率5日变化",
    "f_atr": "ATR(10)/收盘价", "f_amplitude": "当日振幅",
    "f_volatility_10d": "10日波动率(收益std)",
    "f_volatility_20d": "20日波动率(收益std)",
    "f_rsi_14": "RSI(14)", "f_macd": "MACD(12,26,9)",
    "f_bollinger": "布林带位置",
    "f_k": "KDJ-K值(9,3,3)", "f_d": "KDJ-D值(9,3,3)",
    "f_position_20d": "20日价格位置", "f_position_60d": "60日价格位置",
    "f_high_distance": "偏离20日最高价", "f_vpt_5d": "VPT量价趋势5日变化",
}


def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    全向量化批量计算 28 个技术因子。

    输入必须含: code, trade_date, open, high, low, close, volume, amount,
                pct_chg, turnover_rate, volume_ratio, amplitude
    会自行排序。
    """
    need = {"code", "trade_date", "open", "high", "low", "close", "volume",
            "amount", "pct_chg", "turnover_rate", "volume_ratio", "amplitude"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"缺少必要列: {missing}")

    result = df.sort_values(["code", "trade_date"]).reset_index(drop=True)

    # ---------- 工具函数: groupby rolling, 返回对齐到原 df 的 Series ----------
    def roll(col, window, method="mean"):
        g = result.groupby("code")[col]
        if method == "mean":
            return g.rolling(window, min_periods=window).mean().reset_index(level=0, drop=True)
        elif method == "std":
            return g.rolling(window, min_periods=window).std().reset_index(level=0, drop=True)
        elif method == "min":
            return g.rolling(window, min_periods=window).min().reset_index(level=0, drop=True)
        elif method == "max":
            return g.rolling(window, min_periods=window).max().reset_index(level=0, drop=True)
        elif method == "sum":
            return g.rolling(window, min_periods=window).sum().reset_index(level=0, drop=True)

    def shift(col, n):
        return result.groupby("code")[col].shift(n)

    def pct_chg(col, n):
        return result.groupby("code")[col].pct_change(n)

    # ================================================================
    # 1. 动量因子
    # ================================================================
    result["f_mom_1d"] = result["pct_chg"]
    result["f_mom_5d"] = pct_chg("close", 5)
    result["f_mom_10d"] = pct_chg("close", 10)
    result["f_mom_20d"] = pct_chg("close", 20)
    result["f_mom_60d"] = pct_chg("close", 60)

    # ================================================================
    # 2. 均线偏离
    # ================================================================
    _ma5 = roll("close", 5, "mean")
    _ma10 = roll("close", 10, "mean")
    _ma20 = roll("close", 20, "mean")
    _ma60 = roll("close", 60, "mean")

    result["f_vs_ma5"] = (result["close"] - _ma5) / _ma5
    result["f_vs_ma10"] = (result["close"] - _ma10) / _ma10
    result["f_vs_ma20"] = (result["close"] - _ma20) / _ma20
    result["f_vs_ma60"] = (result["close"] - _ma60) / _ma60
    result["f_ma5_ma20"] = (_ma5 - _ma20) / _ma20

    # ================================================================
    # 3. 成交量因子
    # ================================================================
    result["f_vol_ratio"] = result["volume_ratio"]
    result["f_vol_5d"] = pct_chg("volume", 5)
    result["f_vol_10d"] = pct_chg("volume", 10)
    result["f_turnover"] = result["turnover_rate"]
    result["f_turnover_5d"] = pct_chg("turnover_rate", 5)

    # ================================================================
    # 4. 波动率因子 (全向量化 ATR)
    # ================================================================
    _prev_close = shift("close", 1)
    _tr = pd.concat([
        result["high"] - result["low"],
        (result["high"] - _prev_close).abs(),
        (result["low"] - _prev_close).abs(),
    ], axis=1).max(axis=1)

    _atr = _tr.groupby(result["code"].values).rolling(
        10, min_periods=10
    ).mean().reset_index(level=0, drop=True)
    result["f_atr"] = _atr / result["close"].replace(0, np.nan)

    result["f_amplitude"] = result["amplitude"]
    result["f_volatility_10d"] = roll("pct_chg", 10, "std")
    result["f_volatility_20d"] = roll("pct_chg", 20, "std")

    # ================================================================
    # 5. 技术指标
    # ================================================================
    # RSI — 仍需要 Python 循环, 用 transform + numpy 向量化
    result["f_rsi_14"] = result.groupby("code")["close"].transform(_calc_rsi_series)

    # MACD — ewm 用 transform 但比 apply 快得多
    def _ema(col, span):
        return result.groupby("code")[col].transform(
            lambda s: s.ewm(span=span, min_periods=span).mean()
        )
    _ema12 = _ema("close", 12)
    _ema26 = _ema("close", 26)
    _macd_line = _ema12 - _ema26
    _macd_signal = _macd_line.groupby(result["code"].values).transform(
        lambda s: s.ewm(span=9, min_periods=9).mean()
    )
    result["f_macd"] = _macd_line - _macd_signal

    # 布林带
    _close_ma20 = roll("close", 20, "mean")
    _close_std20 = roll("close", 20, "std")
    result["f_bollinger"] = (result["close"] - _close_ma20) / (2 * _close_std20 + 1e-10)

    # KD(9,3,3) — 全向量化
    _low9 = roll("low", 9, "min")
    _high9 = roll("high", 9, "max")
    _rsv = (result["close"] - _low9) / (_high9 - _low9 + 1e-10) * 100
    result["f_k"] = _rsv.groupby(result["code"].values).transform(
        lambda s: s.ewm(alpha=1/3, min_periods=3).mean()
    )
    result["f_d"] = result["f_k"].groupby(result["code"].values).transform(
        lambda s: s.ewm(alpha=1/3, min_periods=3).mean()
    )

    # ================================================================
    # 6. 价格位置
    # ================================================================
    _low20 = roll("low", 20, "min")
    _high20 = roll("high", 20, "max")
    _low60 = roll("low", 60, "min")
    _high60 = roll("high", 60, "max")

    result["f_position_20d"] = (result["close"] - _low20) / (_high20 - _low20 + 1e-10)
    result["f_position_60d"] = (result["close"] - _low60) / (_high60 - _low60 + 1e-10)
    result["f_high_distance"] = (result["close"] - _high20) / _high20

    # ================================================================
    # 7. 量价结合 — VPT
    # ================================================================
    result["_vpt_chg"] = (
        result["volume"]
        * (result["close"] - shift("close", 1))
        / shift("close", 1).replace(0, np.nan)
    ).fillna(0)
    result["_vpt_cum"] = result.groupby("code")["_vpt_chg"].cumsum()
    result["f_vpt_5d"] = result.groupby("code")["_vpt_cum"].pct_change(5)

    # ================================================================
    # 8. 前向收益（目标变量）
    # ================================================================
    fwd_close_3d = shift("close", -3)
    result["fwd_return_3d"] = (fwd_close_3d - result["close"]) / result["close"]
    result["target_3d"] = (result["fwd_return_3d"] > 0).astype(int)

    fwd_close_5d = shift("close", -5)
    result["fwd_return_5d"] = (fwd_close_5d - result["close"]) / result["close"]
    result["target_5d"] = (result["fwd_return_5d"] > 0).astype(int)

    # 清理中间列
    drop_cols = [c for c in result.columns if c.startswith("_")]
    result.drop(columns=drop_cols, inplace=True, errors="ignore")

    return result


def _calc_rsi_series(closes: pd.Series, period: int = 14) -> np.ndarray:
    """RSI(period) 序列 (Wilder 平滑), numpy 向量化逐元素。"""
    arr = closes.values.astype(float)
    n = len(arr)
    rsi = np.full(n, np.nan)
    if n < period + 1:
        return rsi

    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = gains[:period].mean()
    avg_loss = losses[:period].mean()

    for i in range(period, n):
        if i > period:
            d = deltas[i - 1]
            if d > 0:
                avg_gain = (avg_gain * (period - 1) + d) / period
                avg_loss = (avg_loss * (period - 1)) / period
            else:
                avg_gain = (avg_gain * (period - 1)) / period
                avg_loss = (avg_loss * (period - 1) - d) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return rsi
