"""
龙虎榜数据采集模块
数据源：DeepSeek 联网搜索（优先）→ 东方财富公开接口（回退）
"""

import json
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("longhu")

# 东方财富龙虎榜 API
LONGHU_API = "https://push2.eastmoney.com/api/qt/clist/get"
LONGHU_DETAIL_API = "https://datacenter.eastmoney.com/api/data/v1/get"

# DeepSeek 配置（统一从 config.py 导入）
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

# DeepSeek 龙虎榜查询提ofenka
LONGHU_PROMPT = """Task:
你是一位专业的A股龙虎榜数据分析师。请根据互联网公开信息，抓取 {trade_date} 当日A股市场完整的龙虎榜（LHB）数据。你需要对机构席位、北向资金（沪股通/深股通）以及顶级游资营业部进行精准识别、去重、聚合计算与分类排名，最终严格按照指定的JSON模板输出Top数据。

### 数据抓取优先级（必须严格遵守）：
1. 首选东方财富网：https://data.eastmoney.com/stock/lhb.html 和 https://data.eastmoney.com/stock/tradedetail.html
2. 补充来源：同花顺 http://data.10jqka.com.cn/market/longhu/ 、雪球/金融界等
3. 若当日数据尚未完全更新，可抓取最近一个已收盘交易日并在输出中注明。

### 数据处理规则（严格执行）：
1. **聚合逻辑**：同一交易日同一个股/同一营业部出现多次买卖记录，必须先合并净额（买入-卖出）后再进行排名。确保每个榜单中的个股或营业部唯一。
2. **Top 10 统计口径**：
   - 机构与北向：分别统计**净买入额最高的前10只个股** 和 **净卖出额最高（净额为负）的10只个股**。
   - 顶级游资：统计**净买入额最高的前10名营业部** 和 **净卖出额最高的前10名营业部**（不再仅看总成交额）。
3. **金额单位**：所有金额强制转换为「万元」，保留两位小数。
4. **席位精准识别**：
   - 机构席位：仅识别名称中明确包含"机构专用"的席位。
   - 北向席位：仅识别"沪股通专用"或"深股通专用"。
   - 游资席位：优先匹配知名游资标签（章盟主、赵老哥、炒股养家、小鳄鱼、作手新一、宁波桑田路、成都系、西安系等），并在tag字段中标注。
5. **数据真实性**：严禁任何形式的幻觉或伪造。若当日数据不足10条，按实际数量输出，并在highlight_stocks中说明数据完整性。

### 输出要求：
- 禁止包含任何Markdown代码块（如```json）。
- 严禁修改JSON模板中的任何键名，必须100%严格遵守下方模板结构。
- highlight_stocks 部分需给出3-5只核心个股的简短资金博弈逻辑拆解（结合机构/北向/游资合力）。

JSON Template:
{{"data_date": "YYYY-MM-DD",
  "institution_tracking": {{
    "total_net_amount": 0.0,
    "top10_net_buy": [{{"stock_code": "000000", "stock_name": "示例", "net_amount": 0.0}}],
    "top10_net_sell": [{{"stock_code": "000000", "stock_name": "示例", "net_amount": 0.0}}]
  }},
  "hs_connect_tracking": {{
    "total_net_amount": 0.0,
    "top10_net_buy": [{{"stock_code": "000000", "stock_name": "示例", "net_amount": 0.0}}],
    "top10_net_sell": [{{"stock_code": "000000", "stock_name": "示例", "net_amount": 0.0}}]
  }},
  "hot_money_alpha": {{
    "top10_net_buy_brokerages": [
      {{"brokerage": "营业部全称", "tag": "游资标签/无", "net_amount": 0.0}}
    ],
    "top10_net_sell_brokerages": [
      {{"brokerage": "营业部全称", "tag": "游资标签/无", "net_amount": 0.0}}
    ],
    "famous_hot_money_moves": [
      {{"name": "游资名", "brokerage": "营业部", "stock": "代码+名称", "action": "买/卖", "amount": 0.0}}
    ]
  }},
  "highlight_stocks": [
    {{"stock_code": "000000", "stock_name": "示例", "analysis": "资金博弈逻辑拆解"}}
  ]
}}"""

# 龙虎榜类型
BOARD_TYPES = {
    "1": "当日上榜",
    "2": "三日上榜",
    "3": "连续三日",
    "4": "当日跌幅偏离值达7%",
    "5": "当日振幅达15%",
    "6": "当日换手率达20%",
    "7": "当日价格振幅达15%",
    "8": "当日换手率达20%",
    "9": "三日涨幅偏离值达20%",
    "10": "当日涨幅偏离值达7%",
}


def _get_proxy() -> Optional[str]:
    """获取系统代理（仅从环境变量读取，不自动探测端口）"""
    import os
    for var in ["HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"]:
        proxy = os.environ.get(var, "").strip()
        if proxy:
            return proxy
    return None


def _get_db_path() -> Path:
    """获取数据库路径"""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config import DB_PATH
        return Path(DB_PATH)
    except Exception:
        return Path(__file__).resolve().parent.parent / "data" / "quant_storage.db"


def _ensure_table(conn: sqlite3.Connection):
    """确保龙虎榜表存在"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS longhu (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            board_type TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            total_buy REAL DEFAULT 0,
            total_sell REAL DEFAULT 0,
            net_buy REAL DEFAULT 0,
            net_buy_ratio REAL DEFAULT 0,
            buy_detail TEXT DEFAULT '[]',
            sell_detail TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(code, trade_date, board_type)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_longhu_code ON longhu(code)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_longhu_date ON longhu(trade_date)
    """)
    # 兼容旧表：如果缺少 net_buy_ratio 列则添加
    try:
        conn.execute("ALTER TABLE longhu ADD COLUMN net_buy_ratio REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # 龙虎榜缓存表（按日期持久化存储）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS longhu_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_key TEXT NOT NULL,
            content TEXT NOT NULL,
            total_count INTEGER DEFAULT 0,
            timestamp TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(date_key)
        )
    """)
    conn.commit()


def fetch_longhu_list(trade_date: Optional[str] = None) -> list:
    """
    从东方财富获取龙虎榜列表

    Args:
        trade_date: 交易日，格式 YYYYMMDD，默认最新交易日

    Returns:
        list: [{"code": "000001", "name": "平安银行", "reason": "...", ...}]
    """
    if not trade_date:
        trade_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    # 优先使用数据中心 API 按日期查询（支持历史日期）
    stocks = _fetch_longhu_via_datacenter(trade_date)
    if stocks:
        return stocks

    # 回退到 push2 API（仅返回最新交易日数据，日期标签用实际数据日期）
    logger.info(f"数据中心 API 无数据，尝试 push2 API...")
    stocks = _fetch_longhu_via_push2(trade_date)
    if stocks:
        return stocks

    return []


def _fetch_longhu_via_datacenter(trade_date: str) -> list:
    """通过东方财富数据中心 API 按日期获取龙虎榜"""
    proxy = _get_proxy()
    client_kwargs = {"timeout": 15}
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        formatted_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
        with httpx.Client(**client_kwargs) as client:
            params = {
                "reportName": "RPT_LHB_FORMMARKET",
                "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CHANGE_RATE,CLOSE_PRICE,TURNOVERRATE,NET_BUY_AMOUNT,NET_BUY_AMOUNT_RATIO,BUY_AMOUNT,SELL_AMOUNT",
                "filter": f"(TRADE_DATE='{formatted_date}')",
                "pageNumber": "1",
                "pageSize": "500",
                "sortTypes": "-1",
                "sortColumns": "NET_BUY_AMOUNT",
                "source": "WEB",
                "client": "WEB",
            }
            resp = client.get(LONGHU_DETAIL_API, params=params)
            data = resp.json()

            stocks = []
            if data and data.get("result") and data["result"].get("data"):
                for item in data["result"]["data"]:
                    code = str(item.get("SECURITY_CODE", "")).strip()
                    name = str(item.get("SECURITY_NAME_ABBR", "")).strip()
                    if not code or not name:
                        continue

                    total_buy = float(item.get("BUY_AMOUNT", 0) or 0)
                    total_sell = float(item.get("SELL_AMOUNT", 0) or 0)
                    net_buy = float(item.get("NET_BUY_AMOUNT", 0) or 0)
                    net_buy_ratio = float(item.get("NET_BUY_AMOUNT_RATIO", 0) or 0)
                    amount = total_buy + total_sell

                    stocks.append({
                        "code": code,
                        "name": name,
                        "trade_date": trade_date,
                        "board_type": "",
                        "reason": "",
                        "total_buy": round(total_buy, 2),
                        "total_sell": round(total_sell, 2),
                        "net_buy": round(net_buy, 2),
                        "net_buy_ratio": net_buy_ratio,
                        "pct_chg": float(item.get("CHANGE_RATE", 0) or 0),
                        "amount": amount,
                        "turnover_rate": float(item.get("TURNOVERRATE", 0) or 0),
                    })

                logger.info(f"数据中心 API 龙虎榜: 获取到 {len(stocks)} 只股票 ({trade_date})")
                return stocks

        logger.info(f"数据中心 API 无数据: {trade_date}")
        return []

    except Exception as e:
        logger.warning(f"数据中心 API 获取龙虎榜失败: {e}")
        return []


def _fetch_longhu_via_push2(trade_date: str) -> list:
    """通过东方财富 push2 API 获取最新龙虎榜（无日期过滤，仅作降级方案）"""
    proxy = _get_proxy()
    client_kwargs = {"timeout": 15}
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        with httpx.Client(**client_kwargs) as client:
            params = {
                "fid": "f3",
                "po": "1",
                "pz": "100",
                "pn": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fs": "m:0+t:6+f:!50,m:0+t:80+f:!50,m:1+t:2+f:!50,m:1+t:23+f:!50",
                "fields": "f12,f14,f3,f4,f5,f6,f7,f8,f9,f10,f11,f15,f16,f17,f18,f20,f21,f22,f23,f24,f25,f26,f27,f28,f29,f30,f31,f32,f33,f34,f35,f36,f37,f38,f39,f40,f41,f42,f43,f44,f45,f46,f47,f48,f49,f50,f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                "_": str(int(datetime.now().timestamp() * 1000)),
            }
            resp = client.get(LONGHU_API, params=params)
            data = resp.json()

            stocks = []
            if data and data.get("data") and data["data"].get("diff"):
                for item in data["data"]["diff"]:
                    code = str(item.get("f12", "")).strip()
                    name = str(item.get("f14", "")).strip()
                    if not code or not name:
                        continue

                    total_buy = float(item.get("f40", 0) or 0)
                    net_buy = float(item.get("f42", 0) or 0)
                    total_sell = total_buy - net_buy
                    if total_sell < 0:
                        total_sell = 0

                    amount = float(item.get("f6", 0) or 0)
                    turnover_rate = float(item.get("f8", 0) or 0)
                    net_buy_ratio = 0.0
                    if turnover_rate > 0 and amount > 0:
                        circulate_mv = amount / (turnover_rate / 100)
                        if circulate_mv > 0:
                            net_buy_ratio = round((net_buy / circulate_mv) * 100, 4)

                    stocks.append({
                        "code": code,
                        "name": name,
                        "trade_date": trade_date,
                        "board_type": str(item.get("f127", "")),
                        "reason": str(item.get("f100", "")),
                        "total_buy": round(total_buy, 2),
                        "total_sell": round(total_sell, 2),
                        "net_buy": round(net_buy, 2),
                        "net_buy_ratio": net_buy_ratio,
                        "pct_chg": float(item.get("f3", 0) or 0),
                        "amount": amount,
                        "turnover_rate": turnover_rate,
                    })

            logger.info(f"Push2 API 龙虎榜: 获取到 {len(stocks)} 只股票")
            return stocks

    except Exception as e:
        logger.error(f"Push2 API 获取龙虎榜失败: {e}")
        return []


def fetch_longhu_detail(code: str, trade_date: str) -> dict:
    """
    获取个股龙虎榜详情（买卖营业部明细）

    Args:
        code: 股票代码
        trade_date: 交易日 YYYYMMDD

    Returns:
        dict: {"buy": [...], "sell": [...]}
    """
    proxy = _get_proxy()
    client_kwargs = {"timeout": 15}
    if proxy:
        client_kwargs["proxy"] = proxy

    result = {"buy": [], "sell": []}

    try:
        with httpx.Client(**client_kwargs) as client:
            params = {
                "reportName": "RPT_LHB_DETAIL",
                "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,BUY_SELL_TYPE,BUYER_NAME,BUY_AMOUNT,SELL_AMOUNT,NET_BUY_AMOUNT",
                "filter": f'(SECURITY_CODE="{code}")(TRADE_DATE="{trade_date}")',
                "pageNumber": "1",
                "pageSize": "50",
                "sortTypes": "-1",
                "sortColumns": "NET_BUY_AMOUNT",
                "source": "WEB",
                "client": "WEB",
            }
            resp = client.get(LONGHU_DETAIL_API, params=params)
            data = resp.json()

            if data and data.get("result") and data["result"].get("data"):
                for item in data["result"]["data"]:
                    buy_sell = item.get("BUY_SELL_TYPE", "")
                    entry = {
                        "name": item.get("BUYER_NAME", ""),
                        "buy_amount": float(item.get("BUY_AMOUNT", 0) or 0),
                        "sell_amount": float(item.get("SELL_AMOUNT", 0) or 0),
                        "net_amount": float(item.get("NET_BUY_AMOUNT", 0) or 0),
                    }
                    if buy_sell == "1":  # 买入
                        result["buy"].append(entry)
                    elif buy_sell == "2":  # 卖出
                        result["sell"].append(entry)

    except Exception as e:
        logger.error(f"获取 {code} 龙虎榜详情失败: {e}")

    return result


def save_longhu(stocks: list, conn: Optional[sqlite3.Connection] = None):
    """保存龙虎榜数据到数据库"""
    close_conn = False
    if conn is None:
        conn = sqlite3.connect(str(_get_db_path()))
        close_conn = True

    try:
        _ensure_table(conn)
        saved = 0
        for s in stocks:
            try:
                # 尝试获取买卖明细（失败不影响主数据保存）
                buy_detail_json = "[]"
                sell_detail_json = "[]"
                try:
                    detail = fetch_longhu_detail(s["code"], s["trade_date"])
                    if detail:
                        buy_detail_json = json.dumps(detail.get("buy", []), ensure_ascii=False)
                        sell_detail_json = json.dumps(detail.get("sell", []), ensure_ascii=False)
                except Exception:
                    pass

                conn.execute("""
                    INSERT OR REPLACE INTO longhu
                    (code, name, trade_date, board_type, reason, total_buy, total_sell, net_buy, net_buy_ratio, buy_detail, sell_detail)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    s["code"], s["name"], s["trade_date"],
                    s.get("board_type", ""), s.get("reason", ""),
                    s.get("total_buy", 0), s.get("total_sell", 0), s.get("net_buy", 0),
                    s.get("net_buy_ratio", 0),
                    buy_detail_json, sell_detail_json,
                ))
                saved += 1
            except Exception as e:
                logger.warning(f"保存 {s['code']} 龙虎榜失败: {e}")
        conn.commit()
        logger.info(f"龙虎榜数据保存完成: {saved}/{len(stocks)} 条")
    finally:
        if close_conn:
            conn.close()


def get_latest_longhu(limit: int = 200) -> list:
    """
    获取最新龙虎榜数据（按净买入占比降序排列）

    Returns:
        list: [{"code": "...", "name": "...", "net_buy": ..., "net_buy_ratio": ..., ...}]
    """
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT code, name, trade_date, board_type, reason,
                   total_buy, total_sell, net_buy, net_buy_ratio
            FROM longhu
            ORDER BY trade_date DESC, net_buy_ratio DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_longhu_by_codes(codes: list, trade_date: str = "") -> dict:
    """
    批量查询股票是否有龙虎榜记录（含机构参与度）

    Args:
        codes: 股票代码列表
        trade_date: 指定交易日（YYYYMMDD），为空则取最新

    Returns:
        dict: {code: {
            "has_longhu": True/False,
            "net_buy": float,
            "institution_ratio": float,  # 机构参与度 0~1
            "institution_net_buy": float,  # 机构净买入
            ...
        }}
    """
    if not codes:
        return {}

    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join(["?"] * len(codes))
        cursor = conn.cursor()
        if trade_date:
            cursor.execute(f"""
                SELECT code, trade_date, board_type, reason,
                       total_buy, total_sell, net_buy,
                       buy_detail, sell_detail
                FROM longhu
                WHERE code IN ({placeholders}) AND trade_date = ?
                ORDER BY trade_date DESC
            """, [*codes, trade_date])
        else:
            cursor.execute(f"""
                SELECT code, trade_date, board_type, reason,
                       total_buy, total_sell, net_buy,
                       buy_detail, sell_detail
                FROM longhu
                WHERE code IN ({placeholders})
                ORDER BY trade_date DESC
            """, codes)

        result = {}
        for r in cursor.fetchall():
            code = r["code"]
            if code not in result:
                # 解析买卖明细，计算机构参与度
                buy_detail = r["buy_detail"]
                sell_detail = r["sell_detail"]
                inst_buy = 0.0
                inst_sell = 0.0
                total_buy_amount = 0.0
                total_sell_amount = 0.0

                try:
                    if buy_detail:
                        buy_list = json.loads(buy_detail) if isinstance(buy_detail, str) else buy_detail
                        for item in buy_list:
                            amt = float(item.get("buy_amount", 0) or 0)
                            total_buy_amount += amt
                            name = item.get("name", "")
                            # 识别机构席位：名称含"机构"、"基金"、"社保"、"养老"、"保险"、"券商"、"资管"
                            if any(kw in name for kw in ["机构", "基金", "社保", "养老", "保险", "券商", "资管"]):
                                inst_buy += amt
                except Exception:
                    pass

                try:
                    if sell_detail:
                        sell_list = json.loads(sell_detail) if isinstance(sell_detail, str) else sell_detail
                        for item in sell_list:
                            amt = float(item.get("sell_amount", 0) or 0)
                            total_sell_amount += amt
                            name = item.get("name", "")
                            if any(kw in name for kw in ["机构", "基金", "社保", "养老", "保险", "券商", "资管"]):
                                inst_sell += amt
                except Exception:
                    pass

                # 机构参与度 = 机构买卖总额 / 总买卖额
                total_inst = inst_buy + inst_sell
                total_all = total_buy_amount + total_sell_amount
                institution_ratio = round(total_inst / total_all, 4) if total_all > 0 else 0.0
                institution_net_buy = inst_buy - inst_sell

                result[code] = {
                    "has_longhu": True,
                    "trade_date": r["trade_date"],
                    "board_type": r["board_type"],
                    "reason": r["reason"],
                    "total_buy": r["total_buy"],
                    "total_sell": r["total_sell"],
                    "net_buy": r["net_buy"],
                    "institution_ratio": institution_ratio,
                    "institution_net_buy": institution_net_buy,
                }
        # 补全没有龙虎榜的股票
        for code in codes:
            if code not in result:
                result[code] = {
                    "has_longhu": False,
                    "net_buy": 0,
                    "institution_ratio": 0.0,
                    "institution_net_buy": 0.0,
                }
        return result
    finally:
        conn.close()


def _save_longhu_cache(conn: sqlite3.Connection, date_key: str, deepseek_raw: Optional[dict] = None):
    """将指定日期的龙虎榜数据缓存到 longhu_cache 表"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT code, name, trade_date, board_type, reason,
               total_buy, total_sell, net_buy, net_buy_ratio
        FROM longhu
        WHERE trade_date = ?
        ORDER BY net_buy DESC
    """, (date_key,))
    raw = cursor.fetchall()
    if not raw:
        return
    cols = ["code", "name", "trade_date", "board_type", "reason", "total_buy", "total_sell", "net_buy", "net_buy_ratio"]
    rows = [dict(zip(cols, r)) for r in raw]
    
    # 如果有 DeepSeek 原始数据，一起保存
    cache_obj = {"stocks": rows}
    if deepseek_raw:
        cache_obj["deepseek_raw"] = deepseek_raw
    
    content = json.dumps(cache_obj, ensure_ascii=False)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT OR REPLACE INTO longhu_cache (date_key, content, total_count, timestamp)
        VALUES (?, ?, ?, ?)
    """, (date_key, content, len(rows), now_str))
    conn.commit()
    logger.info(f"龙虎榜缓存已保存: {date_key} ({len(rows)} 条)")


def get_longhu_by_date(date_key: str) -> list:
    """从缓存中获取指定日期的龙虎榜数据"""
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT content, total_count, timestamp
            FROM longhu_cache
            WHERE date_key = ?
        """, (date_key,))
        row = cursor.fetchone()
        if row:
            cache_obj = json.loads(row["content"])
            # 兼容新旧格式：新格式是 {"stocks": [...], "deepseek_raw": ...}
            if isinstance(cache_obj, dict) and "stocks" in cache_obj:
                return cache_obj["stocks"]
            return cache_obj if isinstance(cache_obj, list) else []
        return []
    finally:
        conn.close()


def list_longhu_dates() -> list:
    """获取所有有龙虎榜缓存的日期列表（倒序）"""
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT date_key, total_count, timestamp
            FROM longhu_cache
            ORDER BY date_key DESC
        """)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def _fetch_via_deepseek(trade_date: str) -> Optional[dict]:
    """
    通过 DeepSeek 联网搜索获取龙虎榜数据

    Args:
        trade_date: 交易日 YYYYMMDD

    Returns:
        dict: DeepSeek 返回的完整龙虎榜 JSON 数据，或 None
    """
    if not DEEPSEEK_API_KEY:
        logger.warning("未配置 DEEPSEEK_API_KEY，跳过 DeepSeek 龙虎榜查询")
        return None

    try:
        from openai import OpenAI

        date_str = f"{trade_date[:4]}年{trade_date[4:6]}月{trade_date[6:8]}日"
        prompt = LONGHU_PROMPT.format(trade_date=date_str)

        proxy = _get_proxy()
        http_client = httpx.Client(proxy=proxy, timeout=120) if proxy else httpx.Client(timeout=120)

        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            http_client=http_client,
        )

        logger.info(f"正在通过 DeepSeek 联网搜索获取 {date_str} 龙虎榜数据...")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的龙虎榜数据分析师，请严格按照要求的 JSON 格式输出，不要包含 markdown 代码块标记。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )

        if not response or not response.choices:
            logger.warning("DeepSeek 返回空结果")
            return None

        text = response.choices[0].message.content.strip()
        # 去掉可能的 markdown 代码块标记
        text = text.replace("```json", "").replace("```", "").strip()

        data = json.loads(text)
        if data and data.get("data_date"):
            logger.info(f"DeepSeek 龙虎榜数据获取成功: {data.get('data_date')}")
            return data
        else:
            logger.warning("DeepSeek 返回数据格式异常")
            return None

    except Exception as e:
        logger.error(f"DeepSeek 龙虎榜查询失败: {e}")
        return None


def _get_market_snapshot(trade_date: str) -> dict:
    """从 market_snapshot 表获取个股行情数据（换手率、成交额等）
    优先用当天数据，如果当天 turnover_rate 为空则用最近一个有完整数据的交易日
    """
    try:
        conn = sqlite3.connect(str(_get_db_path()))
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # 找最近有 turnover_rate 的交易日（当天或往前）
        c.execute("""
            SELECT DISTINCT trade_date FROM market_snapshot
            WHERE trade_date <= ? AND LENGTH(code) = 6
              AND code NOT LIKE '399%' AND code NOT LIKE '000%'
            ORDER BY trade_date DESC
        """, (trade_date,))
        all_dates = [r[0] for r in c.fetchall()]
        
        rows = None
        for d in all_dates:
            c.execute("""
                SELECT code, turnover_rate, amount, pct_chg, close
                FROM market_snapshot
                WHERE trade_date = ? AND LENGTH(code) = 6
                  AND code NOT LIKE '399%' AND code NOT LIKE '000%'
            """, (d,))
            test_rows = c.fetchall()
            # 检查这个交易日是否有足够多的 turnover_rate 数据（至少 100 条）
            valid_count = sum(1 for r in test_rows if r["turnover_rate"] is not None and r["turnover_rate"] > 0)
            if valid_count >= 100:
                rows = test_rows
                break
        
        if rows is None:
            rows = []
        
        result = {}
        for r in rows:
            result[r["code"]] = {
                "turnover_rate": r["turnover_rate"] or 0,
                "amount": r["amount"] or 0,
                "pct_chg": r["pct_chg"] or 0,
                "close": r["close"] or 0,
            }
        conn.close()
        return result
    except Exception as e:
        logger.warning(f"获取行情快照失败: {e}")
        return {}


def _calc_ratio_from_snapshot(net_buy_val: float, code: str, snapshot: dict) -> float:
    """从行情快照计算净买入占流通市值比例
    流通市值 ≈ 成交额 / (换手率/100)
    占比 = 净买入额 / 流通市值 * 100%
    
    Args:
        net_buy_val: 净买入额（万元）
        code: 股票代码
        snapshot: 行情快照字典
    
    Returns:
        float: 占比（%），如 0.0123 表示 0.0123%
    """
    info = snapshot.get(code, {})
    turnover_rate = info.get("turnover_rate", 0)
    amount = info.get("amount", 0)  # 成交额（元）
    
    if turnover_rate and turnover_rate > 0 and amount and amount > 0:
        # 流通市值（元）= 成交额（元）/ (换手率/100)
        circulate_mv = amount / (turnover_rate / 100)
        # 净买入额（万元）转成元
        net_buy_yuan = net_buy_val * 10000
        if circulate_mv > 0:
            return round((net_buy_yuan / circulate_mv) * 100, 4)
    return 0.0


def _parse_deepseek_longhu(data: dict) -> list:
    """
    将 DeepSeek 返回的龙虎榜数据解析为标准格式

    Args:
        data: DeepSeek 返回的完整 JSON

    Returns:
        list: [{"code": "...", "name": "...", "net_buy": ..., ...}]
    """
    stocks = []
    trade_date = data.get("data_date", "").replace("-", "")
    
    # 从 market_snapshot 获取行情数据用于计算占比
    snapshot = _get_market_snapshot(trade_date)

    def _get_code(item):
        """兼容 DeepSeek 返回的不同字段名"""
        return str(item.get("stock_code", item.get("code", "")))
    def _get_name(item):
        return item.get("stock_name", item.get("name", ""))
    def _get_net_amount(item):
        """获取净买入金额（提示词已要求 DeepSeek 返回万元）"""
        return item.get("net_amount", 0)
    def _get_turnover(item):
        return item.get("turnover_rate", item.get("turnover", 0))
    def _get_pct(item):
        return item.get("closing_change_percent", item.get("pct_chg", 0))

    # 从 institution_tracking 提取机构净买入 TOP10
    inst = data.get("institution_tracking", {})
    for item in inst.get("top10_net_buy", inst.get("top5_net_buy", inst.get("top_5_net_buy", []))):
        net_buy_val = _get_net_amount(item)
        code = _get_code(item)
        ratio = _calc_ratio_from_snapshot(net_buy_val, code, snapshot)
        stocks.append({
            "code": code,
            "name": _get_name(item),
            "trade_date": trade_date,
            "board_type": "机构净买入",
            "reason": f"机构净买入 {net_buy_val:.2f}万",
            "total_buy": net_buy_val if net_buy_val > 0 else 0,
            "total_sell": 0,
            "net_buy": net_buy_val,
            "net_buy_ratio": ratio,
            "pct_chg": 0,
            "turnover_rate": 0,
        })

    # 从 institution_tracking 提取机构净卖出 TOP10
    for item in inst.get("top10_net_sell", inst.get("top3_net_sell", inst.get("top_3_net_sell", []))):
        net_buy_val = _get_net_amount(item)
        code = _get_code(item)
        ratio = _calc_ratio_from_snapshot(net_buy_val, code, snapshot)
        stocks.append({
            "code": code,
            "name": _get_name(item),
            "trade_date": trade_date,
            "board_type": "机构净卖出",
            "reason": f"机构净卖出 {abs(net_buy_val):.2f}万",
            "total_buy": 0,
            "total_sell": abs(net_buy_val),
            "net_buy": net_buy_val,
            "net_buy_ratio": ratio,
            "pct_chg": 0,
            "turnover_rate": 0,
        })

    # 从 hs_connect_tracking 提取北向资金数据
    hs = data.get("hs_connect_tracking", {})
    for item in hs.get("top10_net_buy", hs.get("top5_net_buy", hs.get("top_5_net_buy", []))):
        code = _get_code(item)
        if any(s["code"] == code for s in stocks):
            continue
        net_buy_val = _get_net_amount(item)
        ratio = _calc_ratio_from_snapshot(net_buy_val, code, snapshot)
        stocks.append({
            "code": code,
            "name": _get_name(item),
            "trade_date": trade_date,
            "board_type": "北向净买入",
            "reason": f"北向资金净买入 {net_buy_val:.2f}万",
            "total_buy": net_buy_val if net_buy_val > 0 else 0,
            "total_sell": 0,
            "net_buy": net_buy_val,
            "net_buy_ratio": ratio,
            "pct_chg": 0,
            "turnover_rate": 0,
        })

    # 从 highlight_stocks 提取重点个股
    for item in data.get("highlight_stocks", []):
        code = _get_code(item)
        if not code or any(s["code"] == code for s in stocks):
            continue
        stocks.append({
            "code": code,
            "name": _get_name(item),
            "trade_date": trade_date,
            "board_type": "重点个股",
            "reason": item.get("analysis", item.get("reason", "")),
            "total_buy": 0,
            "total_sell": 0,
            "net_buy": 0,
            "net_buy_ratio": 0,
            "pct_chg": 0,
            "turnover_rate": 0,
        })

    return stocks


def update_longhu():
    """
    更新龙虎榜数据（主入口）
    数据源优先级：东方财富 API（优先）→ DeepSeek 联网搜索（回退）
    获取今天的数据保存到缓存，历史数据不动
    """
    logger.info("=" * 40)
    logger.info("开始更新龙虎榜数据")
    logger.info("=" * 40)

    conn = sqlite3.connect(str(_get_db_path()))
    try:
        _ensure_table(conn)

        total = 0
        saved_date = None
        deepseek_data = None

        # 尝试今天和最近 3 天，取第一个有数据的
        for i in range(0, 4):
            trade_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
            logger.info(f"获取 {trade_date} 龙虎榜...")

            stocks = None

            # 1. 优先东方财富 API（数据更全，含 net_buy_ratio）
            logger.info(f"  尝试东方财富 API...")
            stocks = fetch_longhu_list(trade_date)

            # 2. 东方财富失败，回退 DeepSeek 联网搜索
            if not stocks:
                logger.info(f"  尝试 DeepSeek 联网搜索...")
                deepseek_data = _fetch_via_deepseek(trade_date)
                if deepseek_data:
                    stocks = _parse_deepseek_longhu(deepseek_data)
                    if stocks:
                        logger.info(f"  DeepSeek 获取到 {len(stocks)} 条龙虎榜数据")

            if stocks:
                save_longhu(stocks, conn)
                total += len(stocks)
                saved_date = trade_date
                break

        if saved_date:
            # 成功获取数据后更新缓存（保留历史日期的缓存，不删除）
            _save_longhu_cache(conn, saved_date, deepseek_raw=deepseek_data if deepseek_data else None)
            logger.info(f"龙虎榜更新完成，共 {total} 条记录")
            return {"code": 0, "message": f"龙虎榜更新完成，共 {total} 条", "count": total}
        else:
            logger.warning("所有数据源均无法获取龙虎榜数据，保留上次缓存")
            return {"code": 0, "message": "未获取到新数据，保留上次缓存", "count": 0}
    except Exception as e:
        logger.error(f"更新龙虎榜失败: {e}")
        return {"code": -1, "message": f"更新失败: {e}"}
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    result = update_longhu()
    print(result)

    # 显示最新数据
    data = get_latest_longhu(10)
    print(f"\n最新龙虎榜 TOP 10:")
    for s in data:
        print(f"  {s['code']} {s['name']} 净买入: {s['net_buy']:.2f}万 日期: {s['trade_date']}")
