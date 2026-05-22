"""
模拟止损/止盈优化盈亏比

对 score_board 的每笔交易，逐日跟踪收益
测试不同止损 + 止盈组合的效果
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
import numpy as np
import pandas as pd
from config import DB_PATH

TOP_N = 3
MIN_SCORE = 5
MAX_HOLD = 10

print("=" * 60)
print("  止损/止盈组合优化模拟")
print("=" * 60)

conn = sqlite3.connect(str(DB_PATH))

# 1. 加载评分数据
print("\n[1] 加载评分数据...")
sb = pd.read_sql("""
    SELECT id, REPLACE(date_key, '-', '') as date_key,
           code, name, score, strategy_type
    FROM score_board
    WHERE date_key >= '2026-01-01'
    ORDER BY date_key, score DESC
""", conn)

# 2. 加载行情 — 逐日 pct_chg
print("\n[2] 加载逐日行情...")
price = pd.read_sql("""
    SELECT code, trade_date, pct_chg
    FROM market_snapshot
    WHERE trade_date >= '20251201'
    ORDER BY code, trade_date
""", conn)
conn.close()

price['pct_chg'] = price['pct_chg'] / 100.0

# 每只股票的日收益率序列
code_series = {}
for code, grp in price.groupby('code'):
    code_series[code] = list(zip(grp['trade_date'], grp['pct_chg']))

all_dates = sorted(price['trade_date'].unique())
date_idx = {d: i for i, d in enumerate(all_dates)}

print(f"  score_board: {len(sb)} 行")
print(f"  行情数据: {len(all_dates)} 交易日, {len(code_series)} 只股票")

# 3. 为每笔交易提取逐日收益序列
print("\n[3] 提取逐日收益序列...")

trades = []
missed = 0
for _, row in sb.iterrows():
    code = row['code']
    entry_date = row['date_key']
    di = date_idx.get(entry_date)
    if di is None:
        missed += 1
        continue
    if code not in code_series:
        missed += 1
        continue

    # 找后续交易日的涨跌幅
    daily_rets = []
    # 用全局交易日历找到后续日期
    for i in range(1, MAX_HOLD + 1):
        if di + i >= len(all_dates):
            break
        td = all_dates[di + i]
        # 查这只股票在那天有没有交易
        cs = code_series[code]
        # 需要快速查找，用 dict
        # 改：先构建 dict 缓存
        daily_rets.append(td)
    daily_rets = []

    # 直接从 code_series 取 — 构建 dict
    pct_dict = dict(code_series[code])
    for i in range(1, MAX_HOLD + 1):
        if di + i >= len(all_dates):
            break
        td = all_dates[di + i]
        if td in pct_dict:
            daily_rets.append(pct_dict[td])
        else:
            break  # 停牌，跳过

    if len(daily_rets) < 1:
        missed += 1
        continue

    trades.append({
        'date_key': entry_date,
        'code': code,
        'name': row['name'],
        'score': row['score'],
        'strategy_type': row['strategy_type'],
        'daily_rets': daily_rets,
    })

print(f"  有效交易: {len(trades)}, 跳过: {missed}")

# 4. 测试各种止损/止盈组合
print(f"\n{'='*60}")
print(f"  [4] 止损止盈组合测试")
print(f"{'='*60}")

stop_losses = [0.0, -0.02, -0.03, -0.04, -0.05, -0.07]  # 0 = 不止损
take_profits = [0.0, 0.03, 0.05, 0.08, 0.10, 0.15]

def simulate(trades, stop_loss=0.0, take_profit=0.0, max_hold=5):
    """模拟止损止盈策略"""
    results = []
    for t in trades:
        cum = 1.0
        exited = False
        for day, ret in enumerate(t['daily_rets']):
            if day >= max_hold:
                break
            cum *= (1 + ret)
            if stop_loss < 0 and cum - 1 <= stop_loss:
                results.append(cum - 1)
                exited = True
                break
            if take_profit > 0 and cum - 1 >= take_profit:
                results.append(cum - 1)
                exited = True
                break
        if not exited:
            results.append(cum - 1)
    return results

results_list = []

for sl in stop_losses:
    for tp in take_profits:
        for hold in [3, 5]:
            rets = simulate(trades, sl, tp, hold)
            if len(rets) < 100:
                continue
            wins = sum(1 for r in rets if r > 0)
            n = len(rets)
            wr = wins / n
            avg = np.mean(rets)
            cum = np.sum(rets)
            pos = [r for r in rets if r > 0]
            neg = [r for r in rets if r <= 0]
            pf = abs(sum(pos) / sum(neg)) if sum(neg) != 0 else float('inf')
            sl_label = f"止损{sl*100:.0f}%" if sl < 0 else "不止损"
            tp_label = f"止盈{tp*100:.0f}%" if tp > 0 else "不止盈"
            results_list.append({
                'stop_loss': sl, 'take_profit': tp, 'hold': hold,
                'label': f"{sl_label} {tp_label} hold{hold}d",
                'n': n, 'wr': wr, 'avg': avg, 'cum': cum, 'pf': pf
            })

df_results = pd.DataFrame(results_list)

# 按盈亏比排序
print(f"\n  按盈亏比排序（只看 hold=3 天）：")
print(f"  {'策略':40s} {'样本':>6s} {'胜率':>8s} {'平均':>10s} {'累计':>10s} {'盈亏比':>8s}")
print(f"  {'-'*82}")
top_pf = df_results[df_results['hold'] == 3].sort_values('pf', ascending=False)
for _, r in top_pf.head(15).iterrows():
    print(f"  {r['label']:40s} {r['n']:6d} {r['wr']:7.2%} {r['avg']:+9.2%} {r['cum']:+9.2%} {r['pf']:7.2f}")

print(f"\n  按胜率排序（hold=3）：")
top_wr = df_results[df_results['hold'] == 3].sort_values('wr', ascending=False)
for _, r in top_wr.head(10).iterrows():
    print(f"  {r['label']:40s} {r['n']:6d} {r['wr']:7.2%} {r['avg']:+9.2%} {r['cum']:+9.2%} {r['pf']:7.2f}")

# 5. 最佳组合
print(f"\n{'='*60}")
print(f"  [5] 最佳组合分析")
print(f"{'='*60}")

# 找盈亏比 > 1.3 且样本 > 200 的组合中，累计收益最高的
good = df_results[(df_results['pf'] > 1.3) & (df_results['n'] > 200)]
if len(good) > 0:
    print(f"\n  盈亏比 > 1.3 的组合：")
    for _, r in good.sort_values('cum', ascending=False).head(10).iterrows():
        print(f"  {r['label']:40s} n={r['n']:5d}  wr={r['wr']:.2%}  avg={r['avg']:+.2%}  cum={r['cum']:+.2%}  pf={r['pf']:.2f}")

# 6. 只看 TOP 3 per day 的效果
print(f"\n{'='*60}")
print(f"  [6] 每日 TOP 3 + 最佳止损")
print(f"{'='*60}")

# 取每日评分最高的前3
daily_top = []
for date, grp in pd.DataFrame(trades).groupby('date_key'):
    top3 = grp.sort_values('score', ascending=False).head(TOP_N)
    daily_top.extend(top3.to_dict('records'))

top3_trades = [t for t in daily_top if t['score'] >= MIN_SCORE]
print(f"  每日 TOP{TOP_N} 交易数: {len(top3_trades)}")

# 在 TOP3 上测最好的几个组合
best_combos = [
    (0.0, 0.0, 3, "原始(不止损不止盈,hold3)"),
    (0.0, 0.0, 5, "原始(hold5)"),
    (-0.03, 0.05, 3, "止损3%+止盈5%"),
    (-0.03, 0.08, 3, "止损3%+止盈8%"),
    (-0.04, 0.05, 3, "止损4%+止盈5%"),
    (-0.04, 0.08, 3, "止损4%+止盈8%"),
    (-0.05, 0.08, 5, "止损5%+止盈8% hold5"),
    (-0.03, 0.0, 3, "仅止损3%"),
    (-0.05, 0.0, 3, "仅止损5%"),
    (-0.03, 0.05, 5, "止损3%+止盈5% hold5"),
]

print(f"\n  {'策略':40s} {'样本':>5s} {'胜率':>8s} {'平均':>10s} {'累计':>10s} {'盈亏比':>8s}")
print(f"  {'-'*82}")
for sl, tp, hold, label in best_combos:
    rets = simulate(top3_trades, sl, tp, hold)
    if len(rets) < 10:
        continue
    wins = sum(1 for r in rets if r > 0)
    n = len(rets)
    wr = wins / n
    avg = np.mean(rets)
    cum = np.sum(rets)
    pos = [r for r in rets if r > 0]
    neg = [r for r in rets if r <= 0]
    pf = abs(sum(pos) / sum(neg)) if sum(neg) != 0 else float('inf')
    print(f"  {label:40s} {n:5d} {wr:7.2%} {avg:+9.2%} {cum:+9.2%} {pf:7.2f}")

# 7. B 策略 + 止损
print(f"\n{'='*60}")
print(f"  [7] B 策略 + 止损优化")
print(f"{'='*60}")
b_trades = [t for t in trades if t['strategy_type'] == 'B']
print(f"  B 策略交易数: {len(b_trades)}")

for sl, tp, hold, label in [
    (0.0, 0.0, 3, "B原始(hold3)"),
    (-0.03, 0.05, 3, "B+止损3%+止盈5%"),
    (-0.04, 0.08, 3, "B+止损4%+止盈8%"),
    (-0.03, 0.0, 3, "B+仅止损3%"),
]:
    rets = simulate(b_trades, sl, tp, hold)
    if len(rets) < 10:
        continue
    wins = sum(1 for r in rets if r > 0)
    n = len(rets)
    wr = wins / n
    avg = np.mean(rets)
    cum = np.sum(rets)
    pos = [r for r in rets if r > 0]
    neg = [r for r in rets if r <= 0]
    pf = abs(sum(pos) / sum(neg)) if sum(neg) != 0 else float('inf')
    print(f"  {label:40s} {n:5d} {wr:7.2%} {avg:+9.2%} {cum:+9.2%} {pf:7.2f}")

print(f"\n{'='*60}")
print("  建议")
print(f"{'='*60}")
print("""
基于以上模拟，可以选出一个最佳组合：
  1. 止损线（-3% 或 -4%）：亏到一定程度立即割，防止深套
  2. 止盈线（5% 或 8%）：赚够了落袋
  3. 最大持有天数（3~5天）：超时强制平仓

把这个规则加入实际交易信号输出，就是可执行的策略。
""")
