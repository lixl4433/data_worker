import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sqlite3
from config import DB_PATH
conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

c.execute('SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM market_snapshot')
r = c.fetchone()
print(f'总行数: {r[0]}, 日期范围: {r[1]} ~ {r[2]}')

c.execute('SELECT COUNT(DISTINCT code) FROM market_snapshot')
print(f'股票数量: {c.fetchone()[0]}')

c.execute("""SELECT sector, COUNT(*) FROM market_snapshot
             WHERE sector IS NOT NULL AND sector != ''
             GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 10""")
print('行业分布(top 10):')
for row in c.fetchall():
    print(f'  {row[0]}: {row[1]}')

c.execute('SELECT COUNT(*) FROM market_snapshot WHERE circulate_mv IS NOT NULL AND circulate_mv > 0')
print(f'有流通市值数据: {c.fetchone()[0]}')

# 查看有哪些可用的数值列
c.execute('PRAGMA table_info(market_snapshot)')
print('\n所有列:')
for row in c.fetchall():
    print(f'  {row[1]} ({row[2]})')

conn.close()
