import sys; sys.path.insert(0, '.')
from config import DB_PATH
import sqlite3
conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

new_cols = [
    'sector TEXT DEFAULT ""',
    'strategy_type TEXT DEFAULT ""',
    'entry_date TEXT',
    'exit_date TEXT',
    'stop_loss REAL',
    'take_profit REAL',
    'hold_days_recommended INTEGER DEFAULT 5',
    'holding_days_actual INTEGER',
    'fees REAL DEFAULT 0',
    'net_return_pct REAL',
    'followed_system INTEGER DEFAULT 1',
    'note TEXT DEFAULT ""',
    'source TEXT DEFAULT "ai_scored"',
]

for col_def in new_cols:
    col_name = col_def.split()[0]
    try:
        c.execute(f"ALTER TABLE trade_records ADD COLUMN {col_def}")
        print(f"  Added: {col_name}")
    except Exception as e:
        if "duplicate" in str(e).lower():
            print(f"  Exists: {col_name}")
        else:
            print(f"  Error: {col_name}: {e}")

conn.commit()
conn.close()
print("Done")
