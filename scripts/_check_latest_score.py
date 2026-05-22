import sys, json
sys.path.insert(0, '.')
from config import DB_PATH
import sqlite3
conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()
c.execute("""
    SELECT date_key, code, name, score, strategy_type
    FROM score_board
    WHERE date_key = (SELECT MAX(date_key) FROM score_board)
    ORDER BY score DESC LIMIT 10
""")
rows = c.fetchall()
print(f"最新评分日期: {rows[0][0]}")
print(f"  {'code':>8s} {'name':8s} {'score':>6s} {'type':>4s}")
print("  " + "-" * 30)
for r in rows:
    print(f"  {r[1]:>8s} {r[2]:8s} {r[3]:6.1f} {r[4]:>4s}")
conn.close()
