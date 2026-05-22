import sys; sys.path.insert(0, '.')
from config import DB_PATH
import sqlite3
conn = sqlite3.connect(str(DB_PATH))

# 对比日期格式
sb_date = conn.execute("SELECT DISTINCT date_key FROM score_board LIMIT 5").fetchall()
ms_date = conn.execute("SELECT DISTINCT trade_date FROM market_snapshot LIMIT 5").fetchall()
print("score_board dates:", sb_date)
print("market_snapshot dates:", ms_date)

# 对比代码格式
sb_code = conn.execute("SELECT DISTINCT code FROM score_board LIMIT 5").fetchall()
ms_code = conn.execute("SELECT DISTINCT code FROM market_snapshot LIMIT 5").fetchall()
print("score_board codes:", sb_code)
print("market_snapshot codes:", ms_code)

# 尝试直接联表
rows = conn.execute("""
    SELECT sb.date_key, sb.code, ms.trade_date, ms.code
    FROM score_board sb
    LEFT JOIN market_snapshot ms ON sb.code = ms.code AND sb.date_key = ms.trade_date
    LIMIT 5
""").fetchall()
print("join test:", rows)

# 检查 score_board 第一条
first = conn.execute("SELECT date_key, code FROM score_board LIMIT 3").fetchall()
print("first sb rows:", first)

# 检查 market 中有没有这些股票
for r in first:
    cnt = conn.execute("SELECT COUNT(*) FROM market_snapshot WHERE code=? AND trade_date=?", (r[0], r[1])).fetchone()
    print(f"  code={r[0]} date={r[1]}: found={cnt[0]}")

conn.close()
