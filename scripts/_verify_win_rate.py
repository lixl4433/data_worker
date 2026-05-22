"""
验证评分系统真实胜率

用 score_board 的实际评分数据 + market_snapshot 的后续收益
计算各种持有期的胜率
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
import numpy as np
import pandas as pd
from config import DB_PATH

TOP_N = 3
HOLD_DAYS = 3
MIN_SCORE = 5

print("=" * 60)
print("  评分系统真实胜率验证")
print("=" * 60)

conn = sqlite3.connect(str(DB_PATH))

# 1. 加载评分数据 — 把 date_key 格式转为无横线
print("\n[1] 加载评分数据...")
sb = pd.read_sql("""
    SELECT id, REPLACE(date_key, '-', '') as date_key,
           code, name, score, total_score, strategy_type
    FROM score_board
    WHERE date_key >= '2026-01-01'
    ORDER BY date_key, score DESC
""", conn)
print(f"  score_board: {len(sb)} 行, 日期 {sb['date_key'].min()} ~ {sb['date_key'].max()}")

# 2. 加载行情
print("\n[2] 加载行情数据...")
price = pd.read_sql("""
    SELECT code, trade_date, pct_chg
    FROM market_snapshot
    WHERE trade_date >= '20251201'
    ORDER BY code, trade_date
""", conn)
conn.close()

price['pct_chg'] = price['pct_chg'] / 100.0
print(f"  market_snapshot: {len(price)} 行, {price['code'].nunique()} 只股票")

# 3. 构建快速查找结构
# 每只股票的 {trade_date: pct_chg} 映射
code_pct = {}
for code, grp in price.groupby('code'):
    code_pct[code] = dict(zip(grp['trade_date'], grp['pct_chg']))

# 全局交易日索引（用于找 N 天后）
all_dates = sorted(price['trade_date'].unique())
date_idx = {d: i for i, d in enumerate(all_dates)}

def get_fwd_ret(code, entry_date, days=3):
    """取 entry_date 后 days 个交易日的累积涨跌幅"""
    if code not in code_pct:
        return None
    pct = code_pct[code]
    di = date_idx.get(entry_date)
    if di is None or di + days >= len(all_dates):
        return None
    ret = 1.0
    for i in range(1, days + 1):
        td = all_dates[di + i]
        v = pct.get(td)
        if v is None:   # 停牌
            return None
        ret *= (1 + v)
    return ret - 1.0

# 4. 计算所有收益
print(f"\n[3] 计算持有 {HOLD_DAYS} 天收益...")
results = []
missed = 0
for _, row in sb.iterrows():
    ret = get_fwd_ret(row['code'], row['date_key'], HOLD_DAYS)
    if ret is None:
        missed += 1
        continue
    results.append({
        'date_key': row['date_key'],
        'code': row['code'],
        'name': row['name'],
        'score': row['score'],
        'total_score': row['total_score'],
        'strategy_type': row['strategy_type'],
        'fwd_return': ret,
    })

df = pd.DataFrame(results)
print(f"  成功计算: {len(df)} 行, 跳过(停牌/无数据): {missed}")

if len(df) == 0:
    print("\n  无数据可分析，退出")
    sys.exit(0)

# 5. 统计函数
def calc_stats(subset, label=""):
    n = len(subset)
    if n == 0:
        print(f"\n  {label}: 无数据")
        return
    wins = (subset['fwd_return'] > 0).sum()
    wr = wins / n
    avg = subset['fwd_return'].mean()
    cum = subset['fwd_return'].sum()
    pos_sum = subset.loc[subset['fwd_return'] > 0, 'fwd_return'].sum()
    neg_sum = subset.loc[subset['fwd_return'] <= 0, 'fwd_return'].sum()
    pf = abs(pos_sum / neg_sum) if neg_sum != 0 else float('inf')
    print(f"\n  {label}:")
    print(f"    样本: {n:5d}  |  胜率: {wr:.2%} ({wins}/{n})")
    print(f"    平均: {avg:+.2%}  |  累计: {cum:+.2%}  |  盈亏比: {pf:.2f}")

# 6. 整体胜率
print(f"\n{'='*60}")
print(f"  整体胜率 ({HOLD_DAYS}天持有)")
print(f"{'='*60}")
calc_stats(df, "全部")

# 7. 按策略类型
print(f"\n{'='*60}")
print(f"  按策略类型")
print(f"{'='*60}")
for st in sorted(df['strategy_type'].dropna().unique()):
    calc_stats(df[df['strategy_type'] == st], f"策略 {st}")

# 8. 按评分分档
df['score_range'] = pd.cut(df['score'], bins=[0, 5, 10, 15, 20, 100],
                            labels=['0-5', '5-10', '10-15', '15-20', '20+'], right=False)
print(f"\n{'='*60}")
print(f"  按评分分档胜率")
print(f"{'='*60}")
for label in ['0-5', '5-10', '10-15', '15-20', '20+']:
    sub = df[df['score_range'] == label]
    if len(sub) > 0:
        calc_stats(sub, f"评分 {label}")

# 9. 每日 TOP_N 模拟
print(f"\n{'='*60}")
print(f"  每日选 TOP {TOP_N}  (持有 {HOLD_DAYS} 天)")
print(f"{'='*60}")
daily_top = df.sort_values(['date_key', 'score'], ascending=[True, False])
daily_top = daily_top.groupby('date_key').head(TOP_N)
daily_top = daily_top[daily_top['score'] >= MIN_SCORE]
calc_stats(daily_top, f"每日TOP{TOP_N}")

# 10. 不同持有期对比
print(f"\n{'='*60}")
print(f"  不同持有期对比")
print(f"{'='*60}")
for hold in [1, 3, 5, 10]:
    rets = []
    for _, row in sb.iterrows():
        r = get_fwd_ret(row['code'], row['date_key'], hold)
        if r is not None:
            rets.append(r)
    if rets:
        wr = sum(1 for r in rets if r > 0) / len(rets)
        print(f"  持有 {hold:2d} 天: 胜率 {wr:.2%}  平均 {np.mean(rets):+.2%}  样本 {len(rets)}")

# 11. 月度趋势
print(f"\n{'='*60}")
print(f"  月度胜率趋势")
print(f"{'='*60}")
df['month'] = df['date_key'].str[:6]
for month, sub in sorted(df.groupby('month')):
    wr = (sub['fwd_return'] > 0).mean()
    n = len(sub)
    bar = "█" * max(1, int(wr * 25))
    print(f"  {month}: {wr:.1%} ({n:4d}次) {bar}")

print(f"\n{'='*60}")
print("  完成")
print(f"{'='*60}")
