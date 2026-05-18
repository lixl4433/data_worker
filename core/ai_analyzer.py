"""
AI 分析模块 - 调用 DeepSeek、Kimi 大模型进行股票题材分析

功能：
  1. 调用 DeepSeek API 获取股票题材推荐
  2. 调用 Kimi (Moonshot) API 获取股票题材推荐
  3. 合并两个模型的结果
  4. 对选出的股票进行多因子评分排序
"""

import os
import sys
import json
import re
import logging
import time
from typing import Optional
from datetime import datetime, timedelta

from openai import OpenAI
import httpx


logger = logging.getLogger("ai_analyzer")

# ---------------------------------------------------------------------------
# 配置 - API 密钥（统一从 config.py 导入）
# ---------------------------------------------------------------------------
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, KIMI_API_KEY, KIMI_BASE_URL

# ---------------------------------------------------------------------------
# 代理配置 - 自动检测系统代理，支持 VPN 规则代理
# ---------------------------------------------------------------------------
# 常见的 VPN/代理软件默认端口列表（按优先级排序）
_COMMON_PROXY_PORTS = [7897, 7890, 10809, 10808, 1080, 8080]


def _detect_proxy_from_env() -> Optional[str]:
    """从环境变量检测代理"""
    for var in ["HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"]:
        proxy = os.environ.get(var, "").strip()
        if proxy:
            return proxy
    return None


def _detect_proxy_from_ports() -> Optional[str]:
    """
    检测常见代理软件监听的本地端口。
    尝试连接常见的代理端口，能连上的就认为是代理地址。
    """
    import socket

    for port in _COMMON_PROXY_PORTS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            if result == 0:
                proxy_url = f"http://127.0.0.1:{port}"
                logger.info(f"检测到本地代理端口 {port}，自动使用代理: {proxy_url}")
                return proxy_url
        except Exception:
            continue
    return None


def _get_proxy() -> Optional[str]:
    """
    获取系统代理地址。

    检测顺序：
    1. 环境变量 HTTPS_PROXY / HTTP_PROXY
    2. 扫描常见代理端口（Clash: 7897/7890, v2rayN: 10809, SS: 1080 等）

    如果都没有检测到，返回 None（直连）。
    """
    # 1. 优先使用环境变量
    proxy = _detect_proxy_from_env()
    if proxy:
        logger.info(f"检测到系统代理环境变量: {proxy}")
        return proxy

    # 2. 自动扫描常见代理端口
    proxy = _detect_proxy_from_ports()
    if proxy:
        return proxy

    logger.info("未检测到代理，使用直连")
    return None


def _create_proxied_http_client(timeout: int = 60) -> httpx.Client:
    """
    创建支持代理的 httpx.Client。
    如果系统有代理环境变量，则使用代理；否则直连。
    """
    proxy = _get_proxy()
    if proxy:
        logger.info(f"使用代理: {proxy}")
        return httpx.Client(proxy=proxy, timeout=timeout)
    else:
        return httpx.Client(timeout=timeout)


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------
PROMPT_TEMPLATE = """Current Date: {date}
Role: 你是顶级量化策略与宏观分析专家，擅长利用统计学方法（Z-Score、动能背离、分位点分析、Beta弹性等）从海量实时资讯与长期确定性趋势中，挖掘A股市场未被充分定价的高确定性题材机会。

Task: 
结合以下三条时间线：
1. 短线（0-72小时）
2. 中线产业趋势（1-3个月）
3. 长期宏观蓝图

输出当前最具赚钱效应的10个股票行业题材。每个题材选出5只最相关且最具爆发潜力的个股，总共50只股票。

Processing Protocol:

1. 风险严格过滤：
   - 排除ST股、*ST股、退市整理期个股、近一年有财务造假/违规减持/违规担保/业绩暴雷预告的个股。
   - 排除流通市值低于10亿的微盘股。
   - 排除近30天有重大负面舆情或监管处罚的个股。

2. 技术共振筛选：
   - Price > MA(20)，且 V_current > 1.2 × V_avg_20
   - RSI(14) 处于 50-85
   - 优先选择相对创业板指 Beta 系数 > 1.2 的高弹性细分领域

3. 题材阶段判断：
   - 判断阶段：发酵期 > 爆发期 > 衰退期
   - 优先选择"发酵期"或"早期爆发期"，且有明确时间节点（倒计时效应）、逻辑闭环、预期差较大

4. 实时扫描要求：
   - 最近72小时内全球政策突发、行业提价函、大额订单、关键技术突破、主力资金流向、北向资金异动
   - 未来1-3个月内的重大事件（政策落地、行业会议、周期性节点、国际事件等）

5. 额外实战要求：
   - 每个题材必须是细分赛道（例如"人工智能"需拆成"具身智能/低空经济/算力租赁/视频生成"等）
   - 每只股票必须有具体理由，包含技术面 + 资金面 + 催化剂
   - 优先选择有龙虎榜机构席位、游资活跃或北向资金持续加仓的个股

Input:
- 最近72小时热点新闻和行业事件（JSON或文本形式，标记时间、事件、行业、公司）

{hot_news}

Output Format (必须严格遵守):

{
  "themes": [
    {
      "theme_rank": 1,
      "theme_name": "细分题材名称",
      "stage": "发酵期/爆发期/衰退期",
      "core_drivers": "2-3句核心逻辑",
      "stocks": [
        {
          "rank": 1,
          "code": "600519",
          "name": "贵州茅台",
          "reason": "具体入选理由，包含技术面+资金面+催化剂"
        }
      ]
    }
  ]
}

Constraints:
- 严格基于当前真实市场数据和最新资讯
- 禁止 hallucination
- 如果题材数据不足，则降低排名或放弃
- 输出必须具备直接实战参考价值"""


# ---------------------------------------------------------------------------
# 从数据库获取最新提示词
# ---------------------------------------------------------------------------
def _get_active_prompt() -> str:
    """从数据库 prompt_templates 表获取最新版本的提示词"""
    try:
        import sqlite3
        from pathlib import Path
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from config import DB_PATH
            db_path = DB_PATH
        except Exception:
            db_path = Path(__file__).resolve().parent.parent / "data" / "quant_storage.db"
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM prompt_templates WHERE name = '最新版本'")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        logger.warning(f"从数据库读取提示词失败，使用代码默认: {e}")
    
    # 降级：使用代码中的默认提示词
    return PROMPT_TEMPLATE


# ---------------------------------------------------------------------------
# DeepSeek 调用
# ---------------------------------------------------------------------------
def call_deepseek(hot_news_text: str = "") -> Optional[list]:
    """调用 DeepSeek 模型获取股票推荐"""
    if not DEEPSEEK_API_KEY:
        logger.warning("未配置 DEEPSEEK_API_KEY，跳过 DeepSeek 调用")
        return None

    try:
        http_client = _create_proxied_http_client(timeout=120)
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            http_client=http_client,
        )

        # 从数据库获取最新提示词，填入日期和热点新闻
        prompt = _get_active_prompt()
        today_str = datetime.now().strftime("%Y-%m-%d")
        user_content = prompt.replace("{date}", today_str)
        user_content = user_content.replace("{hot_news}", hot_news_text if hot_news_text else "无热点新闻数据")

        logger.info("正在调用 DeepSeek API...")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的量化策略分析师，请严格按照要求的 JSON 格式输出。"},
                {"role": "user", "content": user_content},
            ],
            temperature=0.7,
            max_tokens=4096,
        )

        if not response or not response.choices:
            logger.warning("DeepSeek 返回空结果")
            return None

        text = response.choices[0].message.content.strip()
        logger.info(f"DeepSeek 返回原始内容长度: {len(text)} 字符")

        stocks = parse_stock_response(text)
        if stocks:
            logger.info(f"DeepSeek 解析成功，获取到 {len(stocks)} 只股票")
        else:
            logger.warning("DeepSeek 返回内容无法解析为有效股票数据")

        return stocks

    except Exception as e:
        logger.error(f"调用 DeepSeek API 异常: {e}")
        return None


# ---------------------------------------------------------------------------
# Kimi (Moonshot) 调用
# ---------------------------------------------------------------------------
def call_kimi(hot_news_text: str = "") -> Optional[list]:
    """调用 Kimi (Moonshot) 模型获取股票推荐"""
    if not KIMI_API_KEY:
        logger.warning("未配置 KIMI_API_KEY，跳过 Kimi 调用")
        return None

    try:
        http_client = _create_proxied_http_client(timeout=120)
        client = OpenAI(
            api_key=KIMI_API_KEY,
            base_url=KIMI_BASE_URL,
            http_client=http_client,
        )

        # 从数据库获取最新提示词，填入日期和热点新闻
        prompt = _get_active_prompt()
        today_str = datetime.now().strftime("%Y-%m-%d")
        user_content = prompt.replace("{date}", today_str)
        user_content = user_content.replace("{hot_news}", hot_news_text if hot_news_text else "无热点新闻数据")

        logger.info("正在调用 Kimi (Moonshot) API...")
        response = client.chat.completions.create(
            model="moonshot-v1-128k",
            messages=[
                {"role": "system", "content": "你是一个专业的量化策略分析师，请严格按照要求的 JSON 格式输出。"},
                {"role": "user", "content": user_content},
            ],
            temperature=0.7,
            max_tokens=4096,
        )

        if not response or not response.choices:
            logger.warning("Kimi 返回空结果")
            return None

        text = response.choices[0].message.content.strip()
        logger.info(f"Kimi 返回原始内容长度: {len(text)} 字符")

        stocks = parse_stock_response(text)
        if stocks:
            logger.info(f"Kimi 解析成功，获取到 {len(stocks)} 只股票")
        else:
            logger.warning("Kimi 返回内容无法解析为有效股票数据")

        return stocks

    except Exception as e:
        logger.error(f"调用 Kimi API 异常: {e}")
        return None


# ---------------------------------------------------------------------------
# 解析响应
# ---------------------------------------------------------------------------
def parse_stock_response(text: str) -> Optional[list]:
    """
    从 AI 返回的文本中解析股票列表。

    新格式（themes 数组）：
    {"themes": [{"theme_rank": 1, "theme_name": "...", "stage": "...", "core_drivers": "...", "stocks": [...]}]}

    兼容旧格式（stocks 数组）：
    {"stocks": [{"rank": 1, "code": "...", "name": "...", "sector": "...", "reason": "..."}]}

    尝试多种解析方式：
    1. 直接解析 JSON
    2. 从 markdown 代码块中提取 JSON
    3. 正则匹配 JSON 结构
    """
    def _extract_stocks_from_themes(data: dict) -> Optional[list]:
        """从 themes 格式中提取所有股票"""
        if "themes" in data and isinstance(data["themes"], list):
            all_stocks = []
            for theme in data["themes"]:
                theme_name = theme.get("theme_name", "")
                stage = theme.get("stage", "")
                core_drivers = theme.get("core_drivers", "")
                stocks = theme.get("stocks", [])
                if isinstance(stocks, list):
                    for s in stocks:
                        s["sector"] = theme_name  # 用题材名称作为 sector
                        s["stage"] = stage
                        s["core_drivers"] = core_drivers
                        all_stocks.append(s)
            if all_stocks:
                return validate_stocks(all_stocks)
        return None

    def _extract_stocks_from_stocks(data: dict) -> Optional[list]:
        """从旧版 stocks 格式中提取股票"""
        if "stocks" in data and isinstance(data["stocks"], list):
            return validate_stocks(data["stocks"])
        return None

    # 方法1：直接解析 JSON
    try:
        data = json.loads(text)
        # 优先新格式 themes
        stocks = _extract_stocks_from_themes(data)
        if stocks:
            return stocks
        # 兼容旧格式 stocks
        stocks = _extract_stocks_from_stocks(data)
        if stocks:
            return stocks
    except json.JSONDecodeError:
        pass

    # 方法2：从 markdown 代码块中提取
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            stocks = _extract_stocks_from_themes(data)
            if stocks:
                return stocks
            stocks = _extract_stocks_from_stocks(data)
            if stocks:
                return stocks
        except json.JSONDecodeError:
            pass

    # 方法3：尝试提取最外层的 JSON 对象
    json_match = re.search(r'\{.*"themes".*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            stocks = _extract_stocks_from_themes(data)
            if stocks:
                return stocks
        except json.JSONDecodeError:
            pass

    json_match = re.search(r'\{.*"stocks".*\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            stocks = _extract_stocks_from_stocks(data)
            if stocks:
                return stocks
        except json.JSONDecodeError:
            pass

    # 方法4：尝试从文本中逐行解析股票信息
    stocks = []
    lines = text.split('\n')
    for line in lines:
        # 匹配类似 "1. 000001 平安银行 题材名" 的格式
        match = re.search(r'(\d+)[.、]\s*[（(]?(\d{6})[)）]?\s+(\S+)', line)
        if match:
            stocks.append({
                "rank": int(match.group(1)),
                "code": match.group(2),
                "name": match.group(3),
                "sector": "",
                "reason": "",
            })

    if stocks:
        return validate_stocks(stocks)

    return None


def validate_stocks(stocks: list) -> list:
    """验证并标准化股票列表"""
    valid = []
    for s in stocks:
        item = {
            "rank": s.get("rank", 0),
            "code": str(s.get("code", "")).strip(),
            "name": str(s.get("name", "")).strip(),
            "sector": str(s.get("sector", "")).strip(),
            "reason": str(s.get("reason", "")).strip(),
        }
        # 简单验证：必须有代码和名称
        if item["code"] and item["name"]:
            valid.append(item)

    # 重新编号
    for i, item in enumerate(valid, 1):
        item["rank"] = i

    return valid


# ---------------------------------------------------------------------------
# 合并结果
# ---------------------------------------------------------------------------
def merge_results(deepseek_stocks: Optional[list], kimi_stocks: Optional[list] = None) -> dict:
    """
    合并两个模型的结果。

    Returns:
        dict: {
            "deepseek": [...],
            "kimi": [...],
            "merged": [...],  # 被多个模型推荐的股票优先
            "timestamp": "...",
        }
    """
    result = {
        "deepseek": deepseek_stocks or [],
        "kimi": kimi_stocks or [],
        "merged": [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 合并逻辑：取两个模型的并集，按推荐次数排序
    stock_map = {}  # code -> {info, count, sources}

    sources = [
        ("deepseek", deepseek_stocks or []),
        ("kimi", kimi_stocks or []),
    ]

    for source, stocks in sources:
        for s in stocks:
            code = s["code"]
            if code not in stock_map:
                stock_map[code] = {
                    "code": code,
                    "name": s["name"],
                    "sector": s.get("sector", ""),
                    "reason": s.get("reason", ""),
                    "count": 0,
                    "sources": [],
                }
            stock_map[code]["count"] += 1
            stock_map[code]["sources"].append(source)
            # 合并 reason
            if s.get("reason") and stock_map[code]["reason"]:
                if s["reason"] not in stock_map[code]["reason"]:
                    stock_map[code]["reason"] += "；" + s["reason"]
            elif s.get("reason"):
                stock_map[code]["reason"] = s["reason"]

    # 按推荐次数排序（被多个模型推荐的排前面），再按 code 排序
    merged = sorted(
        stock_map.values(),
        key=lambda x: (-x["count"], x["code"]),
    )

    for i, item in enumerate(merged, 1):
        item["rank"] = i

    result["merged"] = merged
    return result


# ---------------------------------------------------------------------------
# 对 AI 选出的股票进行多因子评分（复用 web/main.py 中的算法逻辑）
# ---------------------------------------------------------------------------
def score_ai_stocks(ai_stocks: list) -> list:
    """
    对 AI 模型选出的股票，从 market_snapshot 中读取 K 线数据，
    使用多因子算法（涨幅+振幅+量比+位置评分）进行算分排名。

    Args:
        ai_stocks: AI 模型选出的股票列表，每项含 code, name, sector, reason

    Returns:
        list: 评分后的股票列表，每项含 code, name, sector, reason, score 等
    """
    if not ai_stocks:
        return []

    import sqlite3
    from pathlib import Path

    # 使用 config 中的数据库路径配置，自动适配 Windows / Linux
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from config import DB_PATH
        db_path = DB_PATH
    except Exception:
        #  fallback 到硬编码路径
        db_path = Path(__file__).resolve().parent.parent / "data" / "quant_storage.db"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 获取最新交易日
    cursor.execute("SELECT MAX(trade_date) FROM market_snapshot")
    latest_date = cursor.fetchone()[0]
    if not latest_date:
        conn.close()
        logger.warning("market_snapshot 中无数据，无法评分")
        return ai_stocks

    latest_dt = datetime.strptime(latest_date, "%Y%m%d")
    date_5 = (latest_dt - timedelta(days=10)).strftime("%Y%m%d")
    date_20 = (latest_dt - timedelta(days=30)).strftime("%Y%m%d")
    date_250 = (latest_dt - timedelta(days=365)).strftime("%Y%m%d")
    date_rsi = (latest_dt - timedelta(days=30)).strftime("%Y%m%d")  # RSI 需要近14天+缓冲

    # 构建 AI 选出的股票代码列表，用于 SQL IN 查询
    codes = [s["code"] for s in ai_stocks if s.get("code")]
    if not codes:
        conn.close()
        return ai_stocks

    placeholders = ",".join(["?"] * len(codes))

    sql = f"""
        WITH
        -- 近5日统计（放宽：至少1条数据即可）
        stock_stats AS (
            SELECT
                code, name,
                AVG(pct_chg) AS avg_pct_5d,
                AVG(amplitude) AS avg_amp_5d,
                AVG(volume) AS avg_vol_5d,
                AVG(turnover_rate) AS avg_turnover_5d,
                AVG(amount) AS avg_amount_5d,
                (SELECT close FROM market_snapshot sub
                 WHERE sub.code = ms.code AND sub.trade_date <= ?
                 ORDER BY sub.trade_date DESC LIMIT 1) AS latest_close
            FROM market_snapshot ms
            WHERE trade_date >= ? AND trade_date <= ?
              AND ms.code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 1
        ),
        -- 近20日成交量均值（放宽：至少1条数据即可）
        stock_vol_20 AS (
            SELECT code, AVG(volume) AS avg_vol_20d
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
              AND code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 1
        ),
        -- 近1年价格区间（放宽：至少1条数据即可）
        stock_price_range AS (
            SELECT
                code,
                MIN(low) AS year_low,
                MAX(high) AS year_high
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
              AND code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 1
        ),
        -- 近60日箱体（用于箱体底部放量检测）
        stock_box_60 AS (
            SELECT
                code,
                MIN(low) AS box_low,
                MAX(high) AS box_high,
                AVG(volume) AS avg_vol_60d
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
              AND code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 1
        ),
        -- 近5日统计子查询（用于评分因子，避免在SELECT中引用列别名）
        stock_5d_stats AS (
            SELECT
                sub.code,
                ROUND(
                    (SELECT AVG(s2.pct_chg * s2.pct_chg) - AVG(s2.pct_chg) * AVG(s2.pct_chg)
                     FROM market_snapshot s2
                     WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?)
                , 2) AS pct_std_5d,
                (SELECT COUNT(*) FROM market_snapshot s2
                 WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?
                   AND s2.pct_chg > 0) AS up_days_5d,
                ROUND(
                    (SELECT MAX(s2.close) FROM market_snapshot s2
                     WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?)
                    -
                    (SELECT MIN(s2.close) FROM market_snapshot s2
                     WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?)
                , 2) AS max_drawdown_5d,
                (SELECT MIN(s2.low) FROM market_snapshot s2
                 WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS min_low_5d,
                (SELECT MAX(s2.high) FROM market_snapshot s2
                 WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS max_high_5d,
                (SELECT MIN(s2.low) FROM market_snapshot s2
                 WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS support_2,
                (SELECT MAX(s2.high) FROM market_snapshot s2
                 WHERE s2.code = sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS resistance_2
            FROM market_snapshot sub
            WHERE sub.code IN ({placeholders})
            GROUP BY sub.code
        ),
        -- 近20日均线 + ATR（平均真实波幅）用于动态止损
        stock_ma20_atr AS (
            SELECT
                code,
                AVG(close) AS ma20,
                -- ATR简化版：近20日最高-最低的平均值
                AVG(high - low) AS avg_atr
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
              AND code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 5
        ),
        -- 近60日均线（中期趋势参考）
        stock_ma60 AS (
            SELECT
                code,
                AVG(close) AS ma60
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
              AND code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 10
        ),
        -- RSI(14) 计算 + 背离检测
        stock_rsi AS (
            SELECT
                code,
                -- 近14天收盘价序列（用于 RSI 计算）
                (SELECT GROUP_CONCAT(close, ',') FROM (
                    SELECT close FROM market_snapshot s2
                    WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?
                    ORDER BY s2.trade_date ASC
                )) AS close_list,
                -- 近14天最低价（用于底背离检测）
                (SELECT MIN(low) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_low_14d,
                -- 近14天最高价（用于顶背离检测）
                (SELECT MAX(high) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_high_14d,
                -- 近14天最低收盘价（用于底背离检测）
                (SELECT MIN(close) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_close_low_14d,
                -- 近14天最高收盘价（用于顶背离检测）
                (SELECT MAX(close) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_close_high_14d,
                -- 近14天前7天的最低收盘价（用于比较前后半段）
                (SELECT MIN(close) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_close_low_first7,
                -- 近14天后7天的最低收盘价
                (SELECT MIN(close) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_close_low_last7,
                -- 近14天前7天的最高收盘价
                (SELECT MAX(close) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_close_high_first7,
                -- 近14天后7天的最高收盘价
                (SELECT MAX(close) FROM market_snapshot s2
                 WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?) AS rsi_close_high_last7
            FROM market_snapshot rsi_sub
            WHERE rsi_sub.code IN ({placeholders})
            GROUP BY rsi_sub.code
            HAVING COUNT(*) >= 14
        )
        SELECT
            s.code, s.name,
            ROUND(s.avg_pct_5d, 2) AS avg_pct_5d,
            ROUND(s.avg_amp_5d, 2) AS avg_amp_5d,
            ROUND(CAST(s.avg_vol_5d AS REAL) / NULLIF(v.avg_vol_20d, 0), 2) AS vol_ratio,
            ROUND(s.latest_close, 2) AS latest_close,
            ROUND(s.avg_turnover_5d, 2) AS turnover_rate,
            ROUND(s.avg_amount_5d, 2) AS amount,
            -- RSI 背离状态：-1=顶背离(危险), 0=无背离, 1=底背离(机会)
            CASE
                WHEN rsi.rsi_close_low_last7 < rsi.rsi_close_low_first7
                 AND rsi.rsi_close_low_last7 <= rsi.rsi_low_14d * 1.01
                THEN 1
                WHEN rsi.rsi_close_high_last7 > rsi.rsi_close_high_first7
                 AND rsi.rsi_close_high_last7 >= rsi.rsi_high_14d * 0.99
                THEN -1
                ELSE 0
            END AS rsi_divergence,
            d5.pct_std_5d,
            d5.up_days_5d,
            d5.max_drawdown_5d,
            d5.min_low_5d,
            d5.max_high_5d,
            -- 箱体位置：0~1，越接近0越靠近箱体底，越接近1越靠近箱体顶
            ROUND((s.latest_close - bx.box_low) / NULLIF(bx.box_high - bx.box_low, 0), 4) AS box_position,
            -- 距5日高点百分比：0~1，越接近1越靠近5日高点
            ROUND((s.latest_close - d5.min_low_5d) / NULLIF(d5.max_high_5d - d5.min_low_5d, 0), 4) AS close_to_high_pct,
            -- 均线数据
            ROUND(ma.ma20, 2) AS ma20,
            ROUND(ma60.ma60, 2) AS ma60,
            ROUND(ma.avg_atr, 2) AS avg_atr,
            -- 支撑位
            ROUND(bx.box_low, 2) AS support_1,
            ROUND(ma.ma20, 2) AS support_2,
            d5.min_low_5d AS support_3,
            -- 压力位
            ROUND(bx.box_high, 2) AS resistance_1,
            ROUND(ma60.ma60, 2) AS resistance_2,
            d5.max_high_5d AS resistance_3,
            -- 买入价
            ROUND(
                CASE
                    WHEN s.latest_close >= ma.ma20 AND COALESCE(s.avg_pct_5d, 0) > 0
                    THEN ma.ma20 * 1.01
                    WHEN s.latest_close >= bx.box_low AND s.latest_close < ma.ma20
                    THEN bx.box_low * 1.03
                    ELSE NULL
                END
            , 2) AS buy_price,
            -- 卖出价
            ROUND(
                CASE
                    WHEN s.latest_close >= ma.ma20 AND COALESCE(s.avg_pct_5d, 0) > 0
                    THEN MAX(ma60.ma60, bx.box_high) * 0.98
                    WHEN s.latest_close >= bx.box_low AND s.latest_close < ma.ma20
                    THEN bx.box_high * 0.97
                    ELSE ma.ma20 * 0.97
                END
            , 2) AS sell_price,
            -- 止损价
            ROUND(
                CASE
                    WHEN s.latest_close >= ma.ma20 AND COALESCE(s.avg_pct_5d, 0) > 0
                    THEN ma.ma20 - COALESCE(ma.avg_atr, s.latest_close * 0.03) * 2
                    WHEN s.latest_close >= bx.box_low AND s.latest_close < ma.ma20
                    THEN bx.box_low - COALESCE(ma.avg_atr, s.latest_close * 0.03) * 1.5
                    ELSE s.latest_close - COALESCE(ma.avg_atr, s.latest_close * 0.03) * 1
                END
            , 2) AS stop_loss,
            -- 原始因子原始值（Python 层做动态权重评分）
            -- 因子1原始分：趋势强度
            ROUND(
                CASE
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 AND COALESCE(d5.up_days_5d, 0) >= 3 THEN 25
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 AND COALESCE(d5.up_days_5d, 0) >= 2 THEN 18
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 AND COALESCE(d5.up_days_5d, 0) >= 1 THEN 10
                    WHEN COALESCE(s.avg_pct_5d, 0) <= 0 AND COALESCE(d5.up_days_5d, 0) >= 2 THEN 5
                    ELSE 0
                END
            , 2) AS f1_trend,
            -- 因子2原始分：量价配合
            ROUND(
                CASE
                    WHEN (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(v.avg_vol_20d, 0), 0)) > 1.2 AND COALESCE(s.avg_pct_5d, 0) > 0 THEN 20
                    WHEN (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(v.avg_vol_20d, 0), 0)) > 0.8 AND COALESCE(s.avg_pct_5d, 0) > 0 THEN 12
                    WHEN (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(v.avg_vol_20d, 0), 0)) < 0.6 AND COALESCE(s.avg_pct_5d, 0) > 0 THEN 5
                    WHEN (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(v.avg_vol_20d, 0), 0)) > 1.5 AND COALESCE(s.avg_pct_5d, 0) < 0 THEN -15
                    WHEN (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(v.avg_vol_20d, 0), 0)) < 0.8 AND COALESCE(s.avg_pct_5d, 0) < 0 THEN 3
                    ELSE 0
                END
            , 2) AS f2_vol,
            -- 因子3原始分：RSI背离
            ROUND(
                CASE
                    WHEN rsi.rsi_close_low_last7 < rsi.rsi_close_low_first7
                     AND rsi.rsi_close_low_last7 <= rsi.rsi_low_14d * 1.01
                    THEN 20
                    WHEN rsi.rsi_close_high_last7 > rsi.rsi_close_high_first7
                     AND rsi.rsi_close_high_last7 >= rsi.rsi_high_14d * 0.99
                    THEN -15
                    ELSE 10
                END
            , 2) AS f3_rsi,
            -- 因子4原始分：上涨稳定性
            ROUND(
                CASE
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0
                     AND COALESCE(d5.pct_std_5d, 0) < 3
                     AND COALESCE(d5.max_drawdown_5d, 0) / NULLIF(s.latest_close, 0) < 0.05
                    THEN 15
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0
                     AND COALESCE(d5.pct_std_5d, 0) < 5
                     AND COALESCE(d5.max_drawdown_5d, 0) / NULLIF(s.latest_close, 0) < 0.08
                    THEN 10
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 THEN 5
                    WHEN COALESCE(s.avg_pct_5d, 0) < 0
                     AND COALESCE(d5.pct_std_5d, 0) > 5
                    THEN -8
                    ELSE 0
                END
            , 2) AS f4_stability,
            -- 因子5原始分：突破形态
            ROUND(
                CASE
                    WHEN s.latest_close >= d5.max_high_5d * 0.99
                     AND (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(v.avg_vol_20d, 0), 0)) > 1.3
                     AND COALESCE(s.avg_pct_5d, 0) > 0
                    THEN 10
                    WHEN s.latest_close >= d5.max_high_5d * 0.97
                     AND (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(v.avg_vol_20d, 0), 0)) > 1.0
                    THEN 6
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 THEN 3
                    ELSE 0
                END
            , 2) AS f5_breakout,
            -- 因子6原始分：箱体底部放量
            ROUND(
                CASE
                    WHEN (s.latest_close - bx.box_low) / NULLIF(bx.box_high - bx.box_low, 0) <= 0.30
                     AND (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(bx.avg_vol_60d, 0), 0)) >= 2.0
                    THEN 10
                    WHEN (s.latest_close - bx.box_low) / NULLIF(bx.box_high - bx.box_low, 0) <= 0.30
                     AND (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(bx.avg_vol_60d, 0), 0)) >= 1.5
                    THEN 7
                    WHEN (s.latest_close - bx.box_low) / NULLIF(bx.box_high - bx.box_low, 0) <= 0.30
                     AND (CAST(COALESCE(s.avg_vol_5d, 0) AS REAL) / NULLIF(COALESCE(bx.avg_vol_60d, 0), 0)) >= 1.2
                    THEN 4
                    ELSE 0
                END
            , 2) AS f6_box_volume
        FROM stock_stats s
        LEFT JOIN stock_vol_20 v ON s.code = v.code
        LEFT JOIN stock_price_range pr ON s.code = pr.code
        LEFT JOIN stock_box_60 bx ON s.code = bx.code
        LEFT JOIN stock_5d_stats d5 ON s.code = d5.code
        LEFT JOIN stock_ma20_atr ma ON s.code = ma.code
        LEFT JOIN stock_ma60 ma60 ON s.code = ma60.code
        LEFT JOIN stock_rsi rsi ON s.code = rsi.code
        WHERE 1=1
            -- 风险控制：过滤 ST、退市、风险警示股
            AND s.name NOT LIKE '%ST%'
            AND s.name NOT LIKE '%退%'
            AND s.name NOT LIKE '%风险警示%'
            AND s.name NOT LIKE '%S%'  -- 未股改
            -- 技术面风险控制：近5日跌幅过大（>20%）的股票不参与
            AND COALESCE(s.avg_pct_5d, 0) > -20
            -- 成交量异常：近5日均量不能为0
            AND COALESCE(s.avg_vol_5d, 0) > 0
            -- 价格过滤：低于1元（面值退市风险）或高于500元（流动性差）不参与
            AND COALESCE(s.latest_close, 0) >= 1.0
            AND COALESCE(s.latest_close, 0) <= 500.0
    """

    date_60 = (latest_dt - timedelta(days=90)).strftime("%Y%m%d")

    date_20_short = (latest_dt - timedelta(days=25)).strftime("%Y%m%d")

    date_ma20 = (latest_dt - timedelta(days=30)).strftime("%Y%m%d")
    date_ma60 = (latest_dt - timedelta(days=90)).strftime("%Y%m%d")

    # RSI 子查询的日期范围
    date_rsi_start = (latest_dt - timedelta(days=30)).strftime("%Y%m%d")
    date_rsi_end = latest_date
    date_rsi_mid = (latest_dt - timedelta(days=15)).strftime("%Y%m%d")  # 前后半段分界

    params = (
        latest_date,           # 最新收盘价
        date_5, latest_date,   # 近5日
        *codes,                # 股票代码列表
        date_20, latest_date,  # 近20日
        *codes,
        date_250, latest_date, # 近1年
        *codes,
        date_60, latest_date,  # 近60日箱体
        *codes,
        # stock_5d_stats 参数（pct_std_5d, up_days_5d, max_drawdown_5d, min_low_5d, max_high_5d, support_2, resistance_2）
        date_5, latest_date,   # pct_std_5d
        date_5, latest_date,   # up_days_5d
        date_5, latest_date,   # max_drawdown_5d (max)
        date_5, latest_date,   # max_drawdown_5d (min)
        date_5, latest_date,   # min_low_5d
        date_5, latest_date,   # max_high_5d
        date_5, latest_date,   # support_2 (近5日最低价)
        date_5, latest_date,   # resistance_2 (近5日最高价)
        *codes,                # stock_5d_stats 的 WHERE code IN
        # stock_ma20_atr 参数
        date_ma20, latest_date,
        *codes,
        # stock_ma60 参数
        date_ma60, latest_date,
        *codes,
        # stock_rsi 参数（close_list, rsi_low_14d, rsi_high_14d, rsi_close_low_14d, rsi_close_high_14d, 前后半段）
        date_rsi_start, date_rsi_end,  # close_list
        date_rsi_start, date_rsi_end,  # rsi_low_14d
        date_rsi_start, date_rsi_end,  # rsi_high_14d
        date_rsi_start, date_rsi_end,  # rsi_close_low_14d
        date_rsi_start, date_rsi_end,  # rsi_close_high_14d
        date_rsi_start, date_rsi_mid,  # rsi_close_low_first7 (前半段)
        date_rsi_mid, date_rsi_end,    # rsi_close_low_last7 (后半段)
        date_rsi_start, date_rsi_mid,  # rsi_close_high_first7 (前半段)
        date_rsi_mid, date_rsi_end,    # rsi_close_high_last7 (后半段)
        *codes,                        # stock_rsi 的 WHERE code IN
    )

    # ============================================================
    # 第一步：市场环境判定（大盘状态 + 缓冲区 + 赚钱效应）
    # 查上证指数（000001）的最新收盘价和 MA20
    # ============================================================
    market_status = "bull"  # bull=多头, bear=空头/震荡
    try:
        cursor.execute("""
            SELECT close FROM market_snapshot
            WHERE code = '000001' AND trade_date <= ?
            ORDER BY trade_date DESC LIMIT 20
        """, (latest_date,))
        rows = [r[0] for r in cursor.fetchall() if r[0] is not None]
        if len(rows) >= 5:
            latest_idx = rows[0]
            # 缓冲区：需要连续 2 天站上 MA20 才判定为多头
            # 取最近 2 天的收盘价
            close_today = rows[0]
            close_yesterday = rows[1] if len(rows) > 1 else rows[0]
            ma20_idx = sum(rows[:20]) / min(len(rows), 20)
            
            # 条件1：今日收盘价站上 MA20 的 0.5% 以上（缓冲区）
            above_ma20_today = close_today >= ma20_idx * 1.005
            above_ma20_yesterday = close_yesterday >= ma20_idx * 1.005
            
            # 条件2：赚钱效应（涨停家数 > 30 家）
            # 统计当日涨幅 > 9.8% 的股票数量作为涨停家数近似值
            cursor.execute("""
                SELECT COUNT(*) FROM market_snapshot
                WHERE trade_date = ? AND pct_chg >= 9.8
            """, (latest_date,))
            limit_up_count = cursor.fetchone()[0] or 0
            
            if above_ma20_today and above_ma20_yesterday and limit_up_count >= 30:
                market_status = "bull"
                logger.info(f"📊 市场判定：多头（上证 {latest_idx} >= MA20×1.005, 涨停{limit_up_count}家）")
            else:
                market_status = "bear"
                logger.info(f"📊 市场判定：空头/震荡（上证 {latest_idx}, MA20={ma20_idx:.2f}, 涨停{limit_up_count}家）")
        else:
            logger.warning("上证指数数据不足，默认多头市场")
    except Exception as e:
        logger.warning(f"市场环境判定失败，默认多头: {e}")

    cursor.execute(sql, params)
    scored_rows = {row["code"]: dict(row) for row in cursor.fetchall()}

    # 获取龙虎榜数据，叠加龙虎榜因子
    # 日期规则：交易日 20:00-24:00 用当天数据，其他时间用上一个交易日
    longhu_data = {}
    try:
        from core.longhu import get_longhu_by_codes
        now = datetime.now()
        # 判断今天是不是交易日（简单判断：有 market_snapshot 数据就算）
        cursor.execute("SELECT COUNT(*) FROM market_snapshot WHERE trade_date = ?", (now.strftime("%Y%m%d"),))
        is_today_trade_day = cursor.fetchone()[0] > 0
        is_after_8pm = now.hour >= 20
        if is_today_trade_day and is_after_8pm:
            # 交易日 20:00 后，用当天龙虎榜
            longhu_data = get_longhu_by_codes(codes, trade_date=now.strftime("%Y%m%d"))
        else:
            # 其他情况，用上一个交易日
            cursor.execute("""
                SELECT MAX(trade_date) FROM market_snapshot
                WHERE trade_date < ? AND trade_date >= ?
            """, (now.strftime("%Y%m%d"), (now - timedelta(days=10)).strftime("%Y%m%d")))
            prev_date = cursor.fetchone()[0]
            if prev_date:
                longhu_data = get_longhu_by_codes(codes, trade_date=prev_date)
            else:
                longhu_data = get_longhu_by_codes(codes)
    except Exception as e:
        logger.warning(f"获取龙虎榜数据失败: {e}")
    
    conn.close()

    # ============================================================
    # 第二步：对每只股票进行策略分类 + 动态权重评分
    # ============================================================
    result = []
    for s in ai_stocks:
        code = s["code"]
        if code in scored_rows:
            sr = scored_rows[code]
            close = sr["latest_close"]
            box_pos = sr.get("box_position")  # 0~1，箱体位置
            close_to_high = sr.get("close_to_high_pct")  # 0~1，距5日高点百分比

            # ---- 龙虎榜因子（轻权重，按净买入占流通市值比例算分） ----
            lh = longhu_data.get(code, {})
            lh_bonus = 0
            if lh.get("has_longhu"):
                net_buy = lh.get("net_buy", 0)  # 净买入（元）
                # 估算流通市值：成交额 / 换手率（换手率是百分比，如 5% 则传 5）
                turnover_rate = sr.get("turnover_rate")  # 换手率（%）
                amount = sr.get("amount")  # 成交额（元）
                if turnover_rate and turnover_rate > 0 and amount and amount > 0:
                    # 流通市值 ≈ 成交额 / (换手率/100)
                    circulate_mv = amount / (turnover_rate / 100)
                    if circulate_mv > 0:
                        # 净买入占流通市值比例（%）
                        net_buy_ratio = (net_buy / circulate_mv) * 100
                        if net_buy_ratio > 1.0:
                            lh_bonus = 3
                        elif net_buy_ratio > 0.5:
                            lh_bonus = 2
                        elif net_buy_ratio > 0.2:
                            lh_bonus = 1
                        elif net_buy_ratio > 0:
                            lh_bonus = 0.5
                        elif net_buy_ratio < -1.0:
                            lh_bonus = -3
                        elif net_buy_ratio < -0.5:
                            lh_bonus = -2
                        elif net_buy_ratio < -0.2:
                            lh_bonus = -1
                        elif net_buy_ratio < 0:
                            lh_bonus = -0.5

            # ---- 个股策略分类 ----
            # A类（🚀 突破型）：收盘价靠近5日高点（close_to_high > 0.7）或箱体上半部分（box_pos > 0.6）
            # B类（🛡️ 埋伏型）：收盘价靠近箱体底部（box_pos < 0.3）或RSI底背离
            # C类（⏸️ 观望型）：中间地带，不进入 TOP 10
            is_type_a = False
            is_type_b = False
            
            if close_to_high is not None and close_to_high > 0.7:
                is_type_a = True
            if box_pos is not None and box_pos > 0.6:
                is_type_a = True
            # 如果 RSI 底背离，强制归为 B 类
            if sr.get("rsi_divergence") == 1:
                is_type_a = False
                is_type_b = True
            # 箱体底部附近归为 B 类
            if box_pos is not None and box_pos < 0.3:
                is_type_b = True
            
            if is_type_a:
                strategy_type = "A"
            elif is_type_b:
                strategy_type = "B"
            else:
                # C类（观望型）：中间地带，直接过滤，不进入 TOP 10
                continue

            # ---- 动态权重分配 ----
            if market_status == "bull":
                # 多头市场：追涨为主
                if strategy_type == "A":
                    # A类（向上突击型）：突破因子权重高
                    w1, w2, w3, w4, w5, w6 = 0.20, 0.25, 0.10, 0.10, 0.30, 0.05
                else:
                    # B类（低位埋伏型）：RSI背离+箱体底部权重高
                    w1, w2, w3, w4, w5, w6 = 0.20, 0.20, 0.25, 0.10, 0.05, 0.20
            else:
                # 空头/震荡市场：防守为主
                if strategy_type == "A":
                    # A类：量价配合+趋势为主，突破降权
                    w1, w2, w3, w4, w5, w6 = 0.20, 0.25, 0.15, 0.15, 0.15, 0.10
                else:
                    # B类：RSI背离+箱体底部为主，突破几乎屏蔽
                    w1, w2, w3, w4, w5, w6 = 0.20, 0.15, 0.25, 0.10, 0.05, 0.25

            # ---- 计算动态评分 ----
            f1 = sr.get("f1_trend", 0) or 0
            f2 = sr.get("f2_vol", 0) or 0
            f3 = sr.get("f3_rsi", 0) or 0
            f4 = sr.get("f4_stability", 0) or 0
            f5 = sr.get("f5_breakout", 0) or 0
            f6 = sr.get("f6_box_volume", 0) or 0

            # ---- 龙虎榜机构参与度加分（轻权重） ----
            institution_bonus = 0
            if lh.get("has_longhu"):
                inst_ratio = lh.get("institution_ratio", 0.0) or 0.0
                inst_net_buy = lh.get("institution_net_buy", 0.0) or 0.0
                # 机构参与度 > 30% 且机构净买入 > 0
                if inst_ratio > 0.3 and inst_net_buy > 0:
                    institution_bonus = 4
                elif inst_ratio > 0.2 and inst_net_buy > 0:
                    institution_bonus = 2
                elif inst_ratio > 0.1 and inst_net_buy > 0:
                    institution_bonus = 1
                elif inst_ratio > 0.3 and inst_net_buy < 0:
                    institution_bonus = -2  # 机构高参与度但净卖出，危险信号

            # ---- AI题材热度系数 ----
            # 被多个模型推荐的股票获得额外加成
            ai_hot_bonus = 0
            if s.get("ai_count", 1) >= 2:
                ai_hot_bonus = 8  # 被两个模型同时推荐
            elif s.get("ai_count", 1) >= 1:
                ai_hot_bonus = 3  # 被一个模型推荐

            dynamic_score = round(
                f1 * w1 + f2 * w2 + f3 * w3 + f4 * w4 + f5 * w5 + f6 * w6
                + lh_bonus + institution_bonus + ai_hot_bonus, 2
            )

            final_score = dynamic_score
            
            # ============================================================
            # 关键价位最终校验（Python 层，避免 SQL 列别名限制）
            # ============================================================
            close = sr["latest_close"]
            buy_raw = sr.get("buy_price")
            sell_raw = sr.get("sell_price")
            stop_raw = sr.get("stop_loss")
            avg_atr = sr.get("avg_atr") or close * 0.03  # 如果没有ATR，用3%估算
            
            # 最终买入价：如果买入价 > 现价，则取现价*0.99（现价下方1%挂单）
            if buy_raw is not None:
                if buy_raw > close:
                    buy_final = round(close * 0.99, 2)
                else:
                    buy_final = buy_raw
            else:
                buy_final = None
            
            # 最终卖出价：取压力位打折价，但至少比买入价高5%
            if buy_final is not None:
                if sell_raw is not None and sell_raw > buy_final:
                    sell_final = sell_raw
                else:
                    sell_final = round(buy_final * 1.05, 2)
            else:
                sell_final = None
            
            # 非对称止损：
            # A类（突破型）：止损窄（ATR × 1.5），突破失败跑得快
            # B类（埋伏型）：止损宽（ATR × 2.0），给底部震荡留空间
            if buy_final is not None:
                if strategy_type == "A":
                    stop_loss_atr = avg_atr * 1.5
                else:
                    stop_loss_atr = avg_atr * 2.0
                
                if stop_raw is not None and stop_raw < buy_final:
                    # 取 SQL 计算的止损价和非对称止损中较保守的（较高的那个，即止损更早）
                    stop_final = max(stop_raw, round(buy_final - stop_loss_atr, 2))
                else:
                    stop_final = round(buy_final - stop_loss_atr, 2)
                # 止损价不能高于买入价
                if stop_final >= buy_final:
                    stop_final = round(buy_final * 0.95, 2)
            else:
                stop_final = None
            
            # 构建评分说明（每个因子一行）
            score_detail_parts = []
            score_detail_parts.append(f"趋势:{f1}×{w1:.2f}={round(f1*w1,1)}")
            score_detail_parts.append(f"量价:{f2}×{w2:.2f}={round(f2*w2,1)}")
            score_detail_parts.append(f"RSI:{f3}×{w3:.2f}={round(f3*w3,1)}")
            score_detail_parts.append(f"稳定:{f4}×{w4:.2f}={round(f4*w4,1)}")
            score_detail_parts.append(f"突破:{f5}×{w5:.2f}={round(f5*w5,1)}")
            score_detail_parts.append(f"箱体:{f6}×{w6:.2f}={round(f6*w6,1)}")
            if lh_bonus:
                score_detail_parts.append(f"龙虎榜:{lh_bonus}")
            if institution_bonus:
                score_detail_parts.append(f"机构:{institution_bonus}")
            if ai_hot_bonus:
                score_detail_parts.append(f"AI热度:{ai_hot_bonus}")
            score_detail = "\n".join(score_detail_parts) + f"\n总分={final_score}"

            result.append({
                "code": code,
                "name": sr["name"],
                "sector": s.get("sector", ""),
                "reason": s.get("reason", ""),
                "avg_pct_5d": sr["avg_pct_5d"],
                "avg_amp_5d": sr["avg_amp_5d"],
                "vol_ratio": sr["vol_ratio"],
                "latest_close": close,
                "rsi_divergence": sr["rsi_divergence"],
                "score": final_score,
                "score_detail": score_detail,
                "strategy_type": strategy_type,
                "market_status": market_status,
                "longhu_net_buy": lh.get("net_buy", 0),
                "longhu_bonus": lh_bonus,
                "institution_ratio": lh.get("institution_ratio", 0.0),
                "institution_bonus": institution_bonus,
                "ai_hot_bonus": ai_hot_bonus,
                # 关键价位
                "support_1": sr.get("support_1"),
                "support_2": sr.get("support_2"),
                "resistance_1": sr.get("resistance_1"),
                "resistance_2": sr.get("resistance_2"),
                "buy_price": buy_final,
                "sell_price": sell_final,
                "stop_loss": stop_final,
            })
        else:
            # 数据不足或未通过过滤的股票，保留但标记
            result.append({
                "code": code,
                "name": s.get("name", ""),
                "sector": s.get("sector", ""),
                "reason": s.get("reason", ""),
                "avg_pct_5d": None,
                "avg_amp_5d": None,
                "vol_ratio": None,
                "latest_close": None,
                "rsi_divergence": None,
                "score": -9999,  # 无数据排最后
                "score_detail": "",
                "longhu_net_buy": 0,
                "longhu_bonus": 0,
                "support_1": None,
                "support_2": None,
                "resistance_1": None,
                "resistance_2": None,
                "buy_price": None,
                "sell_price": None,
                "stop_loss": None,
            })

    # 按评分排序
    result.sort(key=lambda x: (-x["score"], x["code"]))
    for i, item in enumerate(result, 1):
        item["rank"] = i

    return result


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _build_hot_news_prompt() -> str:
    """
    采集热点新闻，调用 DeepSeek 进行聚合分析，返回聚合后的热点新闻文本。
    格式如：
    [权重：3次] 特朗普访华，黄仁勋随行
    [权重：2次] 算电协同催化电力板块涨停潮
    ...
    """
    try:
        from core.hot_news import collect_all_hot_news, analyze_hot_news_with_deepseek

        # 先采集原始数据
        news = collect_all_hot_news()

        # 构建原始榜单文本
        lines = []
        for source_name, items in news["sources"].items():
            lines.append(f"【{source_name}】")
            for i, item in enumerate(items[:10], 1):
                title = item.get("title", "")
                hot = f" (热度: {item['hot_value']})" if item.get("hot_value") else ""
                lines.append(f"  {i}. {title}{hot}")
            lines.append("")

        raw_text = "\n".join(lines)

        # 调用 DeepSeek 聚合分析
        aggregated = analyze_hot_news_with_deepseek(raw_text)
        if aggregated:
            logger.info(f"DeepSeek 热点聚合完成，{len(aggregated.split(chr(10)))} 行")
            return aggregated
        else:
            # DeepSeek 失败，回退到原始榜单
            logger.warning("DeepSeek 聚合失败，使用原始榜单")
            return raw_text

    except Exception as e:
        logger.warning(f"热点新闻采集失败，跳过: {e}")
        return ""


def run_ai_analysis() -> dict:
    """
    运行完整的 AI 分析流程：
    1. 采集热点新闻
    2. 调用 DeepSeek（带热点新闻上下文）
    3. 调用 Kimi（带热点新闻上下文）
    4. 合并结果
    5. 对合并结果中的股票进行多因子评分排序

    Returns:
        dict: 包含两个模型的结果、合并结果、以及评分排序后的结果
    """
    logger.info("=" * 60)
    logger.info("开始 AI 股票题材分析")
    logger.info("=" * 60)

    # 先采集热点新闻
    logger.info("[0/3] 采集热点新闻...")
    hot_news_text = _build_hot_news_prompt()
    if hot_news_text:
        logger.info(f"热点新闻采集完成，长度: {len(hot_news_text)} 字符")
    else:
        logger.info("无热点新闻数据")

    # 调用 DeepSeek
    logger.info("[1/3] 调用 DeepSeek API...")
    deepseek_stocks = call_deepseek(hot_news_text)
    if deepseek_stocks:
        logger.info(f"DeepSeek 返回 {len(deepseek_stocks)} 只股票")
    else:
        logger.warning("DeepSeek 无返回结果")

    # 调用 Kimi
    logger.info("[2/3] 调用 Kimi (Moonshot) API...")
    kimi_stocks = call_kimi(hot_news_text)
    if kimi_stocks:
        logger.info(f"Kimi 返回 {len(kimi_stocks)} 只股票")
    else:
        logger.warning("Kimi 无返回结果")

    # 合并结果
    logger.info("合并两个模型结果...")
    merged = merge_results(deepseek_stocks, kimi_stocks)

    # 对合并结果中的股票进行多因子评分排序
    logger.info("对 AI 选股进行多因子评分排序...")
    all_ai_stocks = []
    # 收集所有 AI 选出的股票（去重），带 ai_count 用于题材热度系数
    seen_codes = set()
    for s in merged.get("merged", []):
        code = s["code"]
        if code not in seen_codes:
            seen_codes.add(code)
            all_ai_stocks.append({
                "code": code,
                "name": s["name"],
                "sector": s.get("sector", ""),
                "reason": s.get("reason", ""),
                "ai_count": s.get("count", 1),  # 被几个模型推荐
            })
    # 补充 DeepSeek 独有的
    for s in merged.get("deepseek", []):
        code = s["code"]
        if code not in seen_codes:
            seen_codes.add(code)
            all_ai_stocks.append({
                "code": code,
                "name": s["name"],
                "sector": s.get("sector", ""),
                "reason": s.get("reason", ""),
                "ai_count": 1,
            })
    # 补充 Kimi 独有的
    for s in merged.get("kimi", []):
        code = s["code"]
        if code not in seen_codes:
            seen_codes.add(code)
            all_ai_stocks.append({
                "code": code,
                "name": s["name"],
                "sector": s.get("sector", ""),
                "reason": s.get("reason", ""),
                "ai_count": 1,
            })

    logger.info(f"AI 模型共选出 {len(all_ai_stocks)} 只不重复股票")

    # 多因子评分
    scored_stocks = score_ai_stocks(all_ai_stocks)
    valid_count = sum(1 for s in scored_stocks if s["score"] > -9999)
    logger.info(f"评分完成: {valid_count} 只有效数据, {len(scored_stocks) - valid_count} 只数据不足")

    result = {
        "deepseek": deepseek_stocks or [],
        "kimi": kimi_stocks or [],
        "merged": merged.get("merged", []),
        "scored": scored_stocks,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.info(f"分析完成: DeepSeek={len(deepseek_stocks or [])}只, "
                f"Kimi={len(kimi_stocks or [])}只, "
                f"合并={len(merged.get('merged', []))}只, "
                f"评分={len(scored_stocks)}只")

    return result


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    result = run_ai_analysis()
    print(f"\n=== AI 分析 + 多因子评分结果 ===")
    print(f"DeepSeek: {len(result['deepseek'])} 只股票")
    print(f"Kimi: {len(result['kimi'])} 只股票")
    print(f"合并: {len(result['merged'])} 只股票")
    print(f"评分排序: {len(result['scored'])} 只股票")

    if result["scored"]:
        print(f"\n--- 评分排序 TOP 10 ---")
        for s in result["scored"][:10]:
            score_str = f"{s['score']:.2f}" if s['score'] > -9999 else "数据不足"
            print(f"  #{s['rank']} {s['code']} {s['name']} [{s.get('sector', '')}] 评分: {score_str}")
            if s.get("reason"):
                print(f"      理由: {s['reason'][:80]}...")
