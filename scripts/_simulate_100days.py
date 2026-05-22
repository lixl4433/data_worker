"""
模拟100天严格执行：每天选当时最活跃的100只股票评分，保存，回测
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
from config import DB_PATH
from datetime import datetime, timedelta
from core.ai_analyzer import score_ai_stocks
from web.routes.score_board import save_score_board_to_db, load_score_board_from_db
from core.backtest import run_backtest

DAYS = 100
STOCKS_PER_DAY = 100  # 每天选100只活跃股评分
TOP_N = 3
HOLD = 3

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# 获取所有交易日（从最新的往前取100个）
cursor.execute("""
    SELECT DISTINCT trade_date FROM market_snapshot
    ORDER BY trade_date DESC LIMIT ?
""", (DAYS + 20,))  # 多取20天作为缓冲
all_dates = [r["trade_date"] for r in cursor.fetchall()][:DAYS]
all_dates.sort()  # 按时间正序

print(f"交易日: {all_dates[0]} ~ {all_dates[-1]}, 共 {len(all_dates)} 天")

# 先清空 score_board 中这些日期的旧数据
cursor.execute("DELETE FROM score_board")
conn.commit()
conn.close()

total_scored = 0
for i, td in enumerate(all_dates):
    # 获取该日期的活跃股票（按成交额排序）
    conn2 = sqlite3.connect(str(DB_PATH))
    conn2.row_factory = sqlite3.Row
    c2 = conn2.cursor()
    c2.execute("""
        SELECT code, name, '' as sector, '' as reason
        FROM market_snapshot
        WHERE trade_date = ?
          AND name NOT LIKE '%%ST%%'
          AND name NOT LIKE '%%退%%'
          AND close > 5 AND close < 200
        ORDER BY amount DESC
        LIMIT ?
    """, (td, STOCKS_PER_DAY))
    stocks = [dict(r) for r in c2.fetchall()]
    conn2.close()

    if not stocks:
        print(f"  [{i+1}/{DAYS}] {td}: 无数据跳过")
        continue

    # 评分
    scored = score_ai_stocks(stocks, trade_date=td)
    valid = [s for s in scored if s.get("score", -9999) > -9999]
    if not valid:
        print(f"  [{i+1}/{DAYS}] {td}: 评分无效跳过")
        continue

    # 保存
    date_key = f"{td[:4]}-{td[4:6]}-{td[6:]}"
    save_score_board_to_db(date_key, valid)
    total_scored += len(valid)

    if (i + 1) % 20 == 0 or i == 0:
        print(f"  [{i+1}/{DAYS}] {td}: {len(valid)}只评分保存完成")

print(f"\n共评分 {total_scored} 只次股票，开始回测...")

# 回测
bt = run_backtest(top_n=TOP_N, hold_days=HOLD)
if bt.get("code") == 0:
    s = bt["summary"]
    print(f"\n{'='*50}")
    print(f"  回测结果 (top_n={TOP_N}, hold={HOLD})")
    print(f"{'='*50}")
    print(f"  评分日数:  {s['score_dates']}")
    print(f"  交易次数:  {s['total_trades']}")
    print(f"  胜率:      {s['win_rate']}% ({s['win_count']}/{s['total_trades']})")
    print(f"  平均收益:  {s['avg_return']}%")
    print(f"  中位收益:  {s['median_return']}%")
    print(f"  平均赢利:  {s['avg_win']}%  |  平均亏损: {s['avg_loss']}%")
    print(f"  累计收益:  {s['total_return']}%")
    print(f"  盈亏比:    {s['profit_factor']}")
    if bt.get("by_strategy"):
        print(f"\n  按策略类型:")
        for st in bt["by_strategy"]:
            print(f"    {st['strategy_type']}: {st['trades']}次 胜率{st['win_rate']}% 累计{st['total_return']}%")
else:
    print(f"回测失败: {bt.get('message')}")
