"""
检查有效评分的分布
"""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "data" / "quant_storage.db"
conn = sqlite3.connect(str(db))
c = conn.cursor()

c.execute("""
    SELECT date_key, COUNT(*) as total,
           SUM(CASE WHEN score > -9999 THEN 1 ELSE 0 END) as valid,
           SUM(CASE WHEN score <= -9999 THEN 1 ELSE 0 END) as nodata
    FROM score_board GROUP BY date_key ORDER BY date_key
""")
for r in c.fetchall():
    print(f"  {r[0]}: 共{r[1]}条, 有效{r[2]}条, 无数据{r[3]}条")

c.execute("SELECT COUNT(*) as total, ROUND(AVG(score),1) as avg, MIN(score) as min_s, MAX(score) as max_s FROM score_board WHERE score > -9999")
r = c.fetchone()
print(f"\n有效评分: {r['total']}条, 平均{r['avg']}, 范围{r['min_s']}~{r['max_s']}")

conn.close()
