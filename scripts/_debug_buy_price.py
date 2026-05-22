"""
检查买入价与实际收盘价的差异
"""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "data" / "quant_storage.db"
conn = sqlite3.connect(str(db))
c = conn.cursor()

print("=== score_board buy_price vs 当日实际收盘价 ===")
c.execute("""
    SELECT sb.code, sb.name, sb.buy_price as sb_buy, sb.latest_close as sb_close,
           ms.close as actual_close, ms.trade_date
    FROM score_board sb
    JOIN market_snapshot ms ON ms.code = sb.code
    WHERE sb.date_key = '2026-05-19' AND ms.trade_date = '20260519'
    ORDER BY sb.score DESC LIMIT 15
""")
print(f"{'代码':>6} {'名称':>8} {'sb买入价':>10} {'sb最新价':>10} {'实际收盘':>10} {'偏差%':>8}")
for r in c.fetchall():
    code, name, sb_buy, sb_close, actual, date = r
    if sb_buy and actual and actual > 0:
        diff = round((sb_buy - actual) / actual * 100, 1)
    else:
        diff = 0
    print(f"{code:>6} {name:>8} {sb_buy or 0:>10.2f} {sb_close or 0:>10.2f} {actual or 0:>10.2f} {diff:>8.1f}%")

print()
print("=== 301013 利和兴行情 ===")
c.execute("SELECT trade_date, close, pct_chg FROM market_snapshot WHERE code = '301013' AND trade_date >= 20260514 ORDER BY trade_date")
for r in c.fetchall():
    print(f"  {r[0]}: close={r[1]}, pct_chg={r[2]}%")

c.execute("SELECT buy_price, score FROM score_board WHERE code = '301013'")
r = c.fetchone()
if r:
    print(f"score_board buy_price={r[0]}, score={r[1]}")

print()
print("=== 评分最高的股票的买入价 vs 实际收盘价 ===")
# 对所有评分日，取TOP5，看买入价 vs 当天收盘价
c.execute("""
    SELECT sb.date_key, sb.code, sb.name, sb.buy_price, sb.score, ms.close
    FROM (
        SELECT date_key, code, name, buy_price, score,
               ROW_NUMBER() OVER (PARTITION BY date_key ORDER BY score DESC) as rnk
        FROM score_board WHERE score > -9999
    ) sb
    JOIN market_snapshot ms ON ms.code = sb.code AND ms.trade_date = REPLACE(sb.date_key, '-', '')
    WHERE sb.rnk <= 5
    ORDER BY sb.date_key, sb.rnk
""")
print(f"{'日期':>10} {'代码':>6} {'名称':>8} {'买入价':>10} {'评分':>8} {'实际收盘':>10} {'偏差%':>8}")
for r in c.fetchall():
    dk, code, name, bp, score, actual = r
    if bp and actual and actual > 0:
        diff = round((bp - actual) / actual * 100, 1)
    else:
        diff = 0
    print(f"{dk:>10} {code:>6} {name:>8} {bp or 0:>10.2f} {score or 0:>8.1f} {actual or 0:>10.2f} {diff:>8.1f}%")

conn.close()
