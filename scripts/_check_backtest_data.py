"""
检查回测数据可用性
"""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "data" / "quant_storage.db"
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== score_board 日期统计 ===")
c.execute("SELECT date_key, COUNT(*) as cnt FROM score_board GROUP BY date_key ORDER BY date_key")
rows = c.fetchall()
for r in rows:
    print(f"  {r['date_key']}: {r['cnt']} 只股票")
print(f"\n  共 {len(rows)} 个评分日")

print("\n=== 评分分布 ===")
c.execute("SELECT COUNT(*) as total, ROUND(AVG(score),1) as avg_score, MIN(score) as min_s, MAX(score) as max_s FROM score_board")
r = c.fetchone()
print(f"  总记录: {r['total']}, 平均评分: {r['avg_score']}, 范围: {r['min_s']}~{r['max_s']}")

print("\n=== 策略类型分布 ===")
c.execute("SELECT strategy_type, COUNT(*) as cnt FROM score_board GROUP BY strategy_type")
for r in c.fetchall():
    print(f"  {r['strategy_type']}: {r['cnt']}")

print("\n=== market_snapshot 日期范围 ===")
c.execute("SELECT MIN(trade_date) as min_d, MAX(trade_date) as max_d, COUNT(DISTINCT trade_date) as days FROM market_snapshot")
r = c.fetchone()
print(f"  {r['min_d']} ~ {r['max_d']}, 共 {r['days']} 个交易日")

conn.close()
