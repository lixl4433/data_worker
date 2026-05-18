import sqlite3
conn = sqlite3.connect('data/quant_storage.db')
cursor = conn.cursor()

# ai_picks_raw
cursor.execute('SELECT model, raw_data FROM ai_picks_raw')
rows = cursor.fetchall()
print('=== ai_picks_raw ===')
for r in rows:
    print(f'{r[0]}: {r[1][:200]}')

# deepseek
cursor.execute('SELECT code, name, sector, reason FROM ai_picks WHERE model="deepseek" LIMIT 5')
rows = cursor.fetchall()
print()
print('=== deepseek 前5条 ===')
for r in rows:
    print(f'{r[0]} {r[1]} [{r[2]}] {r[3][:60]}')

# kimi
cursor.execute('SELECT code, name, sector, reason FROM ai_picks WHERE model="kimi" LIMIT 5')
rows = cursor.fetchall()
print()
print('=== kimi 前5条 ===')
for r in rows:
    print(f'{r[0]} {r[1]} [{r[2]}] {r[3][:60]}')

conn.close()
