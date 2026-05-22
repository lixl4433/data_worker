import sys; sys.path.insert(0, '.')
from config import DB_PATH
import sqlite3
conn = sqlite3.connect(str(DB_PATH))
rows = conn.execute("SELECT DISTINCT code, name FROM market_snapshot LIMIT 5").fetchall()
conn.close()
stocks = [{'code':r[0], 'name':r[1], 'sector':'test', 'reason':'test'} for r in rows[:3]]

from core.ai_analyzer import score_ai_stocks
r = score_ai_stocks(stocks)
if r:
    for s in r[:3]:
        print(f"{s['code']} {s['name']} type={s['strategy_type']} score={s.get('score')}")
        for k in ('buy_price','sell_price','stop_loss','stop_loss_pct','take_profit_pct','hold_days'):
            print(f"  {k}: {s.get(k)}")
        print(f"  detail: {s.get('score_detail','')[:200]}")
else:
    print("empty result")
