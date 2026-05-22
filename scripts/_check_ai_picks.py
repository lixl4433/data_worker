import sys; sys.path.insert(0, '.')
from config import DB_PATH
import sqlite3
conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

c.execute("PRAGMA table_info(ai_picks)")
cols = c.fetchall()
print("ai_picks 表结构:")
for col in cols:
    print(f"  {col}")

c.execute("SELECT DISTINCT DATE(created_at) as d FROM ai_picks ORDER BY d")
dates = c.fetchall()
print(f"\nai_picks 日期分布: {[r[0] for r in dates]}")

c.execute("SELECT code, name, reason, model FROM ai_picks WHERE model='scored' LIMIT 10")
scored = c.fetchall()
print(f"\nscored 类型 ({len(scored)} 条):")
for r in scored:
    print(f"  {r[0]} {r[1]} {str(r[2])[:50] if r[2] else ''}")

c.execute("SELECT model, COUNT(*) FROM ai_picks GROUP BY model")
counts = c.fetchall()
print(f"\n各模型数量:")
for r in counts:
    print(f"  {r[0]}: {r[1]}")

conn.close()
