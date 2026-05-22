import sys
sys.path.insert(0, '.')
from config import DB_PATH
import sqlite3
conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

# 查看 score_board 的数据来源：是 AI 还是模拟
c.execute("SELECT COUNT(*) FROM score_board")
total = c.fetchone()[0]
print(f"score_board 总行数: {total}")

c.execute("SELECT MIN(date_key), MAX(date_key) FROM score_board")
dr = c.fetchone()
print(f"日期范围: {dr[0]} ~ {dr[1]}")

# 看看原来的 ai_picks 表有没有历史数据
c.execute("SELECT COUNT(*) FROM ai_picks")
ai_total = c.fetchone()[0]
print(f"\nai_picks 总行数: {ai_total}")

if ai_total > 0:
    c.execute("SELECT MIN(created_at), MAX(created_at) FROM ai_picks")
    dr2 = c.fetchone()
    print(f"AI 数据日期范围: {dr2[0]} ~ {dr2[1]}")
    c.execute("SELECT DISTINCT model FROM ai_picks LIMIT 10")
    models = [r[0] for r in c.fetchall()]
    print(f"AI 模型: {models}")

# 看看是否有没被覆盖的原始 AI 评分数据
# 之前模拟删除了 score_board，所以原来的 AI 数据可能已经没了
c.execute("SELECT COUNT(*) FROM score_board WHERE strategy_type IN ('A','B')")
valid = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM score_board WHERE strategy_type IS NULL OR strategy_type = ''")
invalid = c.fetchone()[0]
print(f"\nscore_board 策略分类: 有类型={valid}, 无类型={invalid}")

# 看看最新几条数据的 name，判断是 AI 股还是模拟股
c.execute("SELECT date_key, code, name, score, strategy_type FROM score_board ORDER BY date_key DESC LIMIT 5")
print("\n最新 5 条评分:")
for r in c.fetchall():
    print(f"  {r[0]} {r[1]} {r[2]} 评分={r[3]:.1f} 类型={r[4]}")

# 看最早几条
c.execute("SELECT date_key, code, name, score, strategy_type FROM score_board ORDER BY date_key ASC LIMIT 5")
print("\n最早 5 条评分:")
for r in c.fetchall():
    print(f"  {r[0]} {r[1]} {r[2]} 评分={r[3]:.1f} 类型={r[4]}")

conn.close()
