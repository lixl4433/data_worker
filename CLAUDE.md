# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run the web server
```bash
python main.py
```
Or double-click `start_web.bat`.

The server runs on `http://localhost:7654`.

### Install dependencies
```bash
pip install -r requirements.txt
```

### Debug scripts
```bash
python scripts/_check_ai.py       # Check AI picks in database
python scripts/_test_pytdx.py     # Test Pytdx IP connectivity
python core/ai_analyzer.py        # Run AI analysis standalone
python core/hot_news.py           # Test hot news collection
python core/longhu.py             # Test longhu data collection
```

### API Key configuration
Edit `config.py` to set:
- `DEEPSEEK_API_KEY` + `DEEPSEEK_BASE_URL` (DeepSeek)
- `KIMI_API_KEY` + `KIMI_BASE_URL` (Moonshot/Kimi)
- `TUSHARE_TOKEN` (TuShare Pro for historical data)
- `PUSHPLUS_TOKEN` (optional, for WeChat push)

## Architecture

```
main.py            → FastAPI app entry, port 7654
config.py          → API keys, DB path, Pytdx configs (shared by all modules)
core/              → Business logic (no web dependency)
  ai_analyzer.py   → AI stock analysis (DeepSeek + Kimi calls), multi-factor scoring
  db_manager.py    → DB schema initialization
  hot_news.py      → Hot news from 5 platforms (Douyin, Weibo, EastMoney, THS, WallStreetCN)
  longhu.py        → Dragon & Tiger board data (EastMoney API → DeepSeek fallback)
  data_loader/     → Stock data pipeline (multi-source fault-tolerant)
    __init__.py    → Exports all public functions
    stock_list.py  → Stock list: AKShare → Pytdx → BaoStock → TuShare
    history.py     → Historical K-line download via Pytdx (primary)
    realtime.py    → Real-time quotes: AKShare → Pytdx
    enrich.py      → Data enrichment (turnover rate, amplitude calculation)
    validate.py    → Data integrity validation
    updater.py     → Scheduled update dispatcher (full/incremental/realtime)
    db.py          → DB connection + batch insert helpers
    config.py      → Data loader specific config
web/               → Web layer (FastAPI routes + Jinja2 templates + static files)
  main.py          → (Not used as entry, actual entry is project root main.py)
  config.py        → Web-specific config (logging, DB helpers, paths)
  routes/          → API route handlers
    data_update.py → Data update + strong stock computation
    ai_analysis.py → AI 5-model analysis (DeepSeek/Kimi auto, Gemini/Grok/ChatGPT manual)
    score_board.py → Multi-factor score persistence + retrieval
    hot_news.py    → Hot news API
    longhu.py      → Dragon & tiger board API
    trade_records.py→ Real trade records (CRUD + batch management)
    wx_push.py     → WeChat push via PushPlus
    prompts.py     → Prompt template management
    status.py      → System status endpoints
  templates/       → Jinja2 HTML templates (layout.html + pages/)
  static/          → CSS, JS (vanilla JS, no framework)
data/              → SQLite DB storage
scripts/           → Ad-hoc debug/test scripts
```

## Key Design Decisions

### Data source fallback chain
- **Stock list**: AKShare → Pytdx → BaoStock → TuShare → local cache
- **Historical K-line (full/incremental)**: Pytdx (primary, no rate limit) → AKShare → TuShare → BaoStock
- **Real-time quotes**: AKShare (EastMoney) → Pytdx (multi-IP failover)
- All in `core/data_loader/`.

### Proxy auto-detection
Both `core/ai_analyzer.py` and `core/hot_news.py` detect proxies by:
1. Checking `HTTPS_PROXY` / `HTTP_PROXY` env vars
2. Scanning common proxy ports (7897, 7890, 10809, 10808, 1080, 8080)
Useful for VPN users accessing AI APIs.

### AI analysis pipeline
1. Collect hot news from 5 platforms → optionally aggregate via DeepSeek
2. Call DeepSeek API with news context → get 50 stocks across 10 themes
3. Call Kimi API with same context → same format
4. Merge results (multi-model recommended stocks get AI hot bonus)
5. Multi-factor scoring (6 factors + dynamic weights based on market condition + longhu bonus)
6. Strategy classification: A (breakout), B (ambush), C (wait-and-see, filtered out)

### Multi-factor scoring (6 factors)
| Factor | Range | Description |
|--------|-------|-------------|
| Trend | 0~25 | 5d return + up days |
| Volume-Price | -15~20 | Volume ratio × price action |
| RSI divergence | -15~20 | Hidden/regular divergence |
| Stability | -8~15 | Low volatility uptrend |
| Breakout | 0~10 | Near high + volume surge |
| Box volume | 0~10 | Bottom of range + volume spike |

Dynamic weights adjust based on market condition (bull/bear) + strategy type (A/B).

### Database tables (SQLite, `data/quant_storage.db`)
- **market_snapshot**: Daily K-line data (code, trade_date, open, high, low, close, volume, pct_chg, amplitude, turnover_rate, etc.)
- **ai_picks**: AI model recommendations (model, code, name, sector, reason)
- **score_board**: Multi-factor scoring results per date (code, name, score, buy/sell/stop prices, strategy_type, support/resistance levels)
- **signals**: Legacy signal table
- **trade_records / trade_batches**: Real trade management
- **hot_news**: Cached hot news by date
- **prompt_templates**: Editable AI prompts with name/content/is_default
- **wx_push**: WeChat push subscribers

## Important Notes

- DB file `data/quant_storage.db` is gitignored (`.gitignore` has `*.db`). A `.dbtext` version exists for tracking.
- The `.gitignore` also ignores `.db` files globally — be careful if adding other DBs.
- Python versions 3.9 and 3.12 both appear in `__pycache__` — the project works on either.
- No formal test framework exists; debugging is done via standalone scripts in `scripts/` and `core/*.py __main__` blocks.
- API keys are hardcoded in `config.py` (private project, not open source).
- Frontend is vanilla JS + Jinja2 templates with no JS framework.
- The `_debug_ai.py` and `_debug_ai2.py` in the project root are ad-hoc debugging scripts.