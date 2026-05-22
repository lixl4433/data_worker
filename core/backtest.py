"""
回测模块 - 基于综合评分的历史回测

原理：
  对 score_board 中每个有评分的日期，买入评分最高的 N 只股票，
  持有 M 个交易日后卖出，统计胜率/收益率/资金曲线。

用法：
  python core/backtest.py
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("backtest")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _fmt_date_for_market(d: str) -> str:
    """把 score_board.date_key(YYYY-MM-DD) 转成 market_snapshot.trade_date(YYYYMMDD)"""
    return d.replace("-", "")


def _list_score_dates(cursor, date_from: str = "", date_to: str = "") -> list:
    """获取 score_board 中有评分的日期列表"""
    sql = "SELECT DISTINCT date_key FROM score_board WHERE 1=1"
    params = []
    if date_from:
        sql += " AND date_key >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date_key <= ?"
        params.append(date_to)
    sql += " ORDER BY date_key"
    cursor.execute(sql, params)
    return [r["date_key"] for r in cursor.fetchall()]


def _next_trade_dates(cursor, after_date: str, count: int) -> list:
    """获取 after_date 之后的 count 个交易日（不含当天）"""
    cursor.execute("""
        SELECT DISTINCT trade_date FROM market_snapshot
        WHERE trade_date > ? ORDER BY trade_date LIMIT ?
    """, (after_date, count))
    return [r["trade_date"] for r in cursor.fetchall()]


def _get_close(cursor, code: str, trade_date: str) -> Optional[float]:
    """获取某只股票在指定交易日的收盘价，没有则取最近"""
    cursor.execute(
        "SELECT close FROM market_snapshot WHERE code = ? AND trade_date = ?",
        (code, trade_date)
    )
    row = cursor.fetchone()
    if row and row["close"]:
        return row["close"]
    # 回退：取最近交易日
    cursor.execute("""
        SELECT close FROM market_snapshot
        WHERE code = ? AND trade_date <= ?
        ORDER BY trade_date DESC LIMIT 1
    """, (code, trade_date))
    row = cursor.fetchone()
    return row["close"] if row else None


def run_backtest(date_from: str = "", date_to: str = "",
                 top_n: int = 5, hold_days: int = 5,
                 strategy_type: str = "", min_score: float = 0) -> dict:
    """
    综合评分回测

    Args:
        date_from: 起始日期 YYYY-MM-DD（留空不限）
        date_to:   截止日期 YYYY-MM-DD（留空不限）
        top_n:     每期买入前 N 只
        hold_days: 持有 N 个交易日后卖出
        strategy_type: "A"/"B"/""（全部）
        min_score: 最低评分门槛

    Returns:
        dict: {summary, details, monthly, by_strategy, equity_curve}
    """
    conn = _get_conn()
    cursor = conn.cursor()

    result = {
        "summary": {},
        "details": [],
        "monthly": [],
        "by_strategy": [],
        "equity_curve": [],
    }

    try:
        # ---- 获取评分日期列表 ----
        score_dates = _list_score_dates(cursor, date_from, date_to)
        if not score_dates:
            return {**result, "code": -1, "message": "score_board 中无数据，请先保存综合评分"}

        logger.info(f"回测: {len(score_dates)} 个评分日, top_n={top_n}, hold_days={hold_days}")

        # ---- 逐日期回测 ----
        all_trades = []

        for sd in score_dates:
            trade_date_ymd = _fmt_date_for_market(sd)

            # 取该日期 Top N
            sql = """
                SELECT code, name, score, strategy_type,
                       buy_price, latest_close, sector
                FROM score_board WHERE date_key = ?
            """
            params = [sd]
            if strategy_type:
                sql += " AND strategy_type = ?"
                params.append(strategy_type)
            if min_score > 0:
                sql += " AND score >= ?"
                params.append(min_score)
            sql += " ORDER BY score DESC LIMIT ?"
            params.append(top_n)

            cursor.execute(sql, params)
            stocks = cursor.fetchall()
            if not stocks:
                continue

            # 买入日：评分日的下一个交易日（评分在收盘后，次日才能交易）
            buy_dates = _next_trade_dates(cursor, trade_date_ymd, 1)
            if not buy_dates:
                continue
            buy_date = buy_dates[0]

            # 卖出日：买入日 + hold_days 个交易日
            sell_dates = _next_trade_dates(cursor, buy_date, hold_days)
            if not sell_dates:
                continue
            actual_hold = min(hold_days, len(sell_dates))
            sell_date = sell_dates[actual_hold - 1]

            for s in stocks:
                code = s["code"]
                # 买入价：用买入日的实际收盘价（不使用 score_board 的理论限价）
                buy_price = _get_close(cursor, code, buy_date)
                if not buy_price or buy_price <= 0:
                    continue

                # 卖出价
                sell_price = _get_close(cursor, code, sell_date)
                if not sell_price or sell_price <= 0:
                    continue

                ret = round((sell_price - buy_price) / buy_price * 100, 2)

                all_trades.append({
                    "buy_date": buy_date,
                    "sell_date": sell_date,
                    "code": code,
                    "name": s["name"],
                    "score": round(s["score"], 1) if s["score"] else 0,
                    "strategy_type": s["strategy_type"] or "",
                    "sector": s["sector"] or "",
                    "buy_price": round(buy_price, 2),
                    "sell_price": round(sell_price, 2),
                    "return_pct": ret,
                    "actual_hold_days": actual_hold,
                })

        if not all_trades:
            return {**result, "code": -1, "message": "回测无有效交易（数据不足或条件过严）"}

        # ---- 汇总统计 ----
        returns = [t["return_pct"] for t in all_trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        n = len(returns)
        sorted_ret = sorted(returns)

        summary = {
            "total_trades": n,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(len(wins) / n * 100, 1),
            "avg_return": round(sum(returns) / n, 2),
            "median_return": round(sorted_ret[n // 2], 2),
            "max_return": round(max(returns), 2),
            "min_return": round(min(returns), 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "total_return": round(sum(returns), 2),
            "profit_factor": round(abs(sum(wins) / sum(losses)), 2) if losses and sum(losses) != 0 else 0,
            "score_dates": len(score_dates),
        }

        # ---- 按月统计 ----
        monthly_map = {}
        for t in all_trades:
            mk = t["buy_date"][:6]
            if mk not in monthly_map:
                monthly_map[mk] = {"trades": 0, "wins": 0, "total_return": 0.0}
            monthly_map[mk]["trades"] += 1
            monthly_map[mk]["total_return"] += t["return_pct"]
            if t["return_pct"] > 0:
                monthly_map[mk]["wins"] += 1

        monthly_list = []
        for mk in sorted(monthly_map.keys()):
            m = monthly_map[mk]
            monthly_list.append({
                "month": mk,
                "trades": m["trades"],
                "win_rate": round(m["wins"] / m["trades"] * 100, 1),
                "total_return": round(m["total_return"], 2),
            })

        # ---- 按策略类型统计 ----
        strategy_map = {}
        for t in all_trades:
            st = t["strategy_type"] or "未知"
            if st not in strategy_map:
                strategy_map[st] = {"trades": 0, "wins": 0, "total_return": 0.0}
            strategy_map[st]["trades"] += 1
            strategy_map[st]["total_return"] += t["return_pct"]
            if t["return_pct"] > 0:
                strategy_map[st]["wins"] += 1

        strategy_list = []
        for st in sorted(strategy_map.keys()):
            s = strategy_map[st]
            strategy_list.append({
                "strategy_type": st,
                "trades": s["trades"],
                "win_rate": round(s["wins"] / s["trades"] * 100, 1),
                "total_return": round(s["total_return"], 2),
            })

        # ---- 资金曲线 ----
        trades_sorted = sorted(all_trades, key=lambda x: x["sell_date"])
        cum = 0.0
        curve = []
        for t in trades_sorted:
            cum += t["return_pct"]
            curve.append({
                "date": t["sell_date"],
                "cumulative_return": round(cum, 2),
            })

        return {
            "code": 0,
            "summary": summary,
            "details": all_trades,
            "monthly": monthly_list,
            "by_strategy": strategy_list,
            "equity_curve": curve,
            "params": {
                "date_from": date_from or "最早",
                "date_to": date_to or "最新",
                "top_n": top_n,
                "hold_days": hold_days,
                "strategy_type": strategy_type or "全部",
                "min_score": min_score,
            },
        }

    except Exception as e:
        logger.error(f"回测异常: {e}", exc_info=True)
        return {**result, "code": -1, "message": f"回测异常: {e}"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    import argparse
    parser = argparse.ArgumentParser(description="综合评分回测")
    parser.add_argument("--top-n", type=int, default=5, help="每期买入前 N 只")
    parser.add_argument("--hold", type=int, default=5, help="持有 N 个交易日")
    parser.add_argument("--strategy", default="", help="策略类型 A/B")
    parser.add_argument("--min-score", type=float, default=0, help="最低评分")
    parser.add_argument("--from", dest="date_from", default="", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--to", dest="date_to", default="", help="截止日期 YYYY-MM-DD")
    args = parser.parse_args()

    result = run_backtest(
        date_from=args.date_from,
        date_to=args.date_to,
        top_n=args.top_n,
        hold_days=args.hold,
        strategy_type=args.strategy,
        min_score=args.min_score,
    )

    if result.get("code") == -1:
        print(f"❌ {result['message']}")
        exit(1)

    s = result["summary"]
    print(f"\n{'='*50}")
    print(f"  回测结果")
    print(f"{'='*50}")
    print(f"  交易次数:  {s['total_trades']}")
    print(f"  胜率:      {s['win_rate']}% ({s['win_count']}/{s['total_trades']})")
    print(f"  平均收益:  {s['avg_return']}%")
    print(f"  中位收益:  {s['median_return']}%")
    print(f"  平均赢利:  {s['avg_win']}%  |  平均亏损: {s['avg_loss']}%")
    print(f"  最大收益:  {s['max_return']}%  |  最小收益: {s['min_return']}%")
    print(f"  累计收益:  {s['total_return']}%")
    print(f"  盈亏比:    {s['profit_factor']}")
    print(f"  评分日数:  {s['score_dates']}")
    print(f"{'='*50}")

    if result["by_strategy"]:
        print(f"\n--- 按策略类型 ---")
        for st in result["by_strategy"]:
            print(f"  {st['strategy_type']}: {st['trades']}次 胜率{st['win_rate']}% 累计{st['total_return']}%")

    if result["monthly"]:
        print(f"\n--- 按月统计 ---")
        for m in result["monthly"]:
            print(f"  {m['month']}: {m['trades']}次 胜率{m['win_rate']}% 累计{m['total_return']}%")

    print(f"\n--- 最近交易 ---")
    for t in result["details"][-5:]:
        print(f"  {t['buy_date']}→{t['sell_date']} {t['code']} {t['name']} "
              f"({t['strategy_type']})  {t['return_pct']:+.2f}%")
