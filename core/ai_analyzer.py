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


def _assess_market_state(latest_date: str, cursor) -> dict:
    """
    多因子市场状态判定（5因子综合评分）

    评分因子和范围：
      趋势位置 0~30: 上证指数相对于 MA20/MA60 的位置和 MA20 方向
      市场宽度 0~25: 上涨家数占比
      量能配合 0~20: 上证成交量相对 20 日均量的比值
      赚钱效应 -5~15: 涨停家数 - 跌停家数
      趋势质量 0~10: 连续站上/跌破 MA20 的天数

    总分 0~100: >=65 多头, 35~65 震荡, <35 空头
    """
    result = {
        "state": "震荡",
        "score": 50,
        "factors": {},
        "summary": "",
        "idx_close": 0,
    }

    try:
        dt = datetime.strptime(latest_date, "%Y%m%d")

        # ---- Factor 1: 指数趋势位置 (0~30) ----
        cursor.execute("""
            SELECT trade_date, close FROM market_snapshot
            WHERE code = '000001' AND trade_date <= ?
            ORDER BY trade_date DESC LIMIT 60
        """, (latest_date,))
        idx_rows = cursor.fetchall()

        f1 = 15
        idx_close = 0

        if len(idx_rows) >= 20:
            closes = [r["close"] for r in idx_rows if r["close"] is not None]
            if len(closes) >= 20:
                idx_close = closes[0]
                ma20 = sum(closes[:20]) / 20
                ma60 = sum(closes[:min(60, len(closes))]) / min(60, len(closes))

                above_ma20 = idx_close >= ma20
                above_ma60 = idx_close >= ma60

                # MA20 方向：对比前 20 日和最近 20 日的 MA20
                if len(closes) >= 40:
                    ma20_recent = sum(closes[:20]) / 20
                    ma20_prior = sum(closes[20:40]) / 20
                    ma20_rising = ma20_recent > ma20_prior * 1.003
                    ma20_falling = ma20_recent < ma20_prior * 0.997
                else:
                    ma20_rising = True
                    ma20_falling = False

                if above_ma20 and ma20_rising and above_ma60:
                    f1 = 30
                elif above_ma20 and ma20_rising:
                    f1 = 25
                elif above_ma20 and not ma20_falling:
                    f1 = 20
                elif above_ma20 and ma20_falling:
                    f1 = 15
                elif not above_ma20 and not ma20_falling:
                    f1 = 10
                elif not above_ma20 and ma20_falling and above_ma60:
                    f1 = 5
                else:
                    f1 = 0

        result["factors"]["趋势位置"] = f1
        result["idx_close"] = idx_close

        # ---- Factor 2: 市场宽度 (0~25) ----
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) as advances
            FROM market_snapshot
            WHERE trade_date = ? AND LENGTH(code) = 6
              AND code NOT LIKE '399%' AND code NOT LIKE '000%'
        """, (latest_date,))
        br = cursor.fetchone()
        total = br["total"] or 0
        advances = br["advances"] or 0

        if total > 0:
            ratio = advances / total
            if ratio >= 0.70:
                f2 = 25
            elif ratio >= 0.60:
                f2 = 20
            elif ratio >= 0.50:
                f2 = 15
            elif ratio >= 0.40:
                f2 = 10
            elif ratio >= 0.30:
                f2 = 5
            else:
                f2 = 0
        else:
            f2 = 12

        result["factors"]["市场宽度"] = f2

        # ---- Factor 3: 量能配合 (0~20) ----
        cursor.execute("""
            SELECT volume FROM market_snapshot
            WHERE code = '000001' AND trade_date = ?
        """, (latest_date,))
        vrow = cursor.fetchone()

        if vrow and vrow["volume"] and vrow["volume"] > 0:
            cur_vol = vrow["volume"]
            thirty_days_ago = (dt - timedelta(days=35)).strftime("%Y%m%d")
            cursor.execute("""
                SELECT AVG(volume) as avg_vol FROM market_snapshot
                WHERE code = '000001' AND trade_date < ? AND trade_date >= ?
            """, (latest_date, thirty_days_ago))
            arow = cursor.fetchone()
            avg_vol = arow["avg_vol"] if arow and arow["avg_vol"] else cur_vol

            if avg_vol > 0:
                vr = cur_vol / avg_vol
                if vr >= 1.5:
                    f3 = 20
                elif vr >= 1.2:
                    f3 = 18
                elif vr >= 1.0:
                    f3 = 14
                elif vr >= 0.8:
                    f3 = 10
                elif vr >= 0.6:
                    f3 = 5
                else:
                    f3 = 0
            else:
                f3 = 10
        else:
            f3 = 10

        result["factors"]["量能"] = f3

        # ---- Factor 4: 赚钱效应 (-5~15) ----
        cursor.execute("""
            SELECT
                SUM(CASE WHEN pct_chg >= 9.8 THEN 1 ELSE 0 END) as limit_up,
                SUM(CASE WHEN pct_chg <= -9.8 THEN 1 ELSE 0 END) as limit_down
            FROM market_snapshot
            WHERE trade_date = ? AND LENGTH(code) = 6
              AND code NOT LIKE '399%' AND code NOT LIKE '000%'
              AND name NOT LIKE '%ST%' AND name NOT LIKE '%退%'
        """, (latest_date,))
        lr = cursor.fetchone()
        limit_up = lr["limit_up"] or 0
        limit_down = lr["limit_down"] or 0

        net_limit = limit_up - limit_down

        if net_limit >= 30:
            f4 = 15
        elif net_limit >= 15:
            f4 = 12
        elif net_limit >= 5:
            f4 = 8
        elif net_limit >= 0:
            f4 = 4
        elif net_limit >= -10:
            f4 = 0
        else:
            f4 = -5

        result["factors"]["赚钱效应"] = f4

        # ---- Factor 5: 趋势质量 (0~10) ----
        f5 = 5

        if len(idx_rows) >= 20:
            closes = [r["close"] for r in idx_rows if r["close"] is not None]
            if len(closes) >= 20:
                ma20_val = sum(closes[:20]) / 20
                cursor.execute("""
                    SELECT close FROM market_snapshot
                    WHERE code = '000001' AND trade_date <= ?
                    ORDER BY trade_date DESC LIMIT 8
                """, (latest_date,))
                recent_closes = [r["close"] for r in cursor.fetchall() if r["close"] is not None]

                above_count = sum(1 for c in recent_closes if c >= ma20_val)
                below_count = len(recent_closes) - above_count

                if above_count >= 6:
                    f5 = 10
                elif above_count >= 4:
                    f5 = 8
                elif above_count >= 2:
                    f5 = 6
                elif below_count >= 6:
                    f5 = 1
                elif below_count >= 4:
                    f5 = 2
                else:
                    f5 = 4

        result["factors"]["趋势质量"] = f5

        # ---- 综合 ----
        total = f1 + f2 + f3 + f4 + f5
        total = max(0, min(100, total))

        if total >= 65:
            result["state"] = "bull"
        elif total >= 35:
            result["state"] = "震荡"
        else:
            result["state"] = "bear"

        result["score"] = total

        detail = ", ".join(f"{k}:{v}" for k, v in result["factors"].items())
        result["summary"] = f"评分={total}, {detail}"

        return result

    except Exception as e:
        logger.warning(f"市场状态判定失败，默认震荡: {e}")
        return result


# ---------------------------------------------------------------------------
# RSI(14) 计算工具函数
# ---------------------------------------------------------------------------
def _calc_rsi(closes: list, period: int = 14) -> float:
    """计算 RSI(14) 指标，返回 0~100"""
    if not closes or len(closes) < period + 1:
        return 50.0
    prices = [c for c in closes if c is not None and c > 0]
    if len(prices) < period + 1:
        return 50.0

    # 初始平滑平均
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period

    # Wilder 平滑
    for i in range(period + 1, len(prices)):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            avg_gain = (avg_gain * (period - 1) + diff) / period
            avg_loss = (avg_loss * (period - 1)) / period
        else:
            avg_gain = (avg_gain * (period - 1)) / period
            avg_loss = (avg_loss * (period - 1) - diff) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _rsi_divergence(price_trend: str, rsi_trend: str) -> int:
    """检测 RSI 背离。返回 1=底背离, -1=顶背离, 0=无背离"""
    if price_trend == "lower_low" and rsi_trend == "higher_low":
        return 1   # 底背离：价格新低但 RSI 未新低 → 看涨
    if price_trend == "higher_high" and rsi_trend == "lower_high":
        return -1  # 顶背离：价格新高但 RSI 未新高 → 看跌
    return 0


# ---------------------------------------------------------------------------
# 对 AI 选出的股票进行多因子评分（复用 web/main.py 中的算法逻辑）
# ---------------------------------------------------------------------------
def score_ai_stocks(ai_stocks: list, trade_date: str = "") -> list:
    """
    对 AI 模型选出的股票，从 market_snapshot 中读取 K 线数据，
    使用多因子算法（涨幅+振幅+量比+位置评分）进行算分排名。

    Args:
        ai_stocks: AI 模型选出的股票列表，每项含 code, name, sector, reason
        trade_date: 目标交易日 YYYYMMDD（留空则用最新交易日）

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

    # 获取目标交易日
    if trade_date:
        latest_date = trade_date
    else:
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
            SELECT code,
                   (SELECT GROUP_CONCAT(close, ',') FROM (
                       SELECT close FROM market_snapshot s2
                       WHERE s2.code = rsi_sub.code AND s2.trade_date >= ? AND s2.trade_date <= ?
                       ORDER BY s2.trade_date ASC
                   )) AS close_list
            FROM market_snapshot rsi_sub
            WHERE rsi_sub.code IN ({placeholders})
            GROUP BY rsi_sub.code
            HAVING COUNT(*) >= 15
        ),
        -- 近10日趋势
        stock_stats_10d AS (
            SELECT code,
                   AVG(pct_chg) AS avg_pct_10d,
                   SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) AS up_days_10d
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
              AND code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 3
        ),
        -- 近20日趋势
        stock_stats_20d AS (
            SELECT code,
                   AVG(pct_chg) AS avg_pct_20d
            FROM market_snapshot
            WHERE trade_date >= ? AND trade_date <= ?
              AND code IN ({placeholders})
            GROUP BY code
            HAVING COUNT(*) >= 5
        )
        SELECT
            s.code, s.name,
            ROUND(s.avg_pct_5d, 2) AS avg_pct_5d,
            ROUND(s.avg_amp_5d, 2) AS avg_amp_5d,
            ROUND(CAST(s.avg_vol_5d AS REAL) / NULLIF(v.avg_vol_20d, 0), 2) AS vol_ratio,
            ROUND(s.latest_close, 2) AS latest_close,
            ROUND(s.avg_turnover_5d, 2) AS turnover_rate,
            ROUND(s.avg_amount_5d, 2) AS amount,
            -- RSI 计算用收盘价序列（Python 层计算真实 RSI）
            rsi.close_list,
            d5.pct_std_5d,
            d5.up_days_5d,
            d5.max_drawdown_5d,
            d5.min_low_5d,
            d5.max_high_5d,
            -- 多周期趋势数据
            s10.avg_pct_10d,
            s10.up_days_10d,
            s20.avg_pct_20d,
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
            -- 因子1原始分：5日趋势基础分（0-15），多周期加分在 Python 层
            ROUND(
                CASE
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 AND COALESCE(d5.up_days_5d, 0) >= 3 THEN 15
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 AND COALESCE(d5.up_days_5d, 0) >= 2 THEN 10
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 AND COALESCE(d5.up_days_5d, 0) >= 1 THEN 5
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
            -- 因子3原始分：Python 层基于真实 RSI(14) 计算，SQL 返回中性值
            10 AS f3_rsi,
            -- 因子4原始分：Python 层基于 Sharpe 比计算，SQL 返回基础值
            ROUND(
                CASE
                    WHEN COALESCE(s.avg_pct_5d, 0) > 0 THEN 5
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
        LEFT JOIN stock_stats_10d s10 ON s.code = s10.code
        LEFT JOIN stock_stats_20d s20 ON s.code = s20.code
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

    # RSI + 多周期趋势 子查询的日期范围
    date_rsi_start = (latest_dt - timedelta(days=30)).strftime("%Y%m%d")
    date_rsi_end = latest_date
    date_10d_start = (latest_dt - timedelta(days=15)).strftime("%Y%m%d")

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
        # stock_rsi 参数（close_list）
        date_rsi_start, date_rsi_end,  # close_list
        *codes,                        # stock_rsi 的 WHERE code IN
        # stock_stats_10d 参数
        date_10d_start, latest_date,
        *codes,
        # stock_stats_20d 参数（复用 date_20 = 30天前）
        date_20, latest_date,
        *codes,
    )

    # ============================================================
    # 第一步：市场环境判定（多因子综合评分）
    # 5 因子：趋势位置(0~30) + 市场宽度(0~25) + 量能(0~20) + 赚钱效应(-5~15) + 趋势质量(0~10)
    # 总分 0~100：>=65 多头, 35~65 震荡, <35 空头
    # ============================================================
    market_assessment = _assess_market_state(latest_date, cursor)
    market_status = market_assessment["state"]
    market_score = market_assessment["score"]
    logger.info(f"📊 市场判定：{market_status}（评分 {market_score}/100）- {market_assessment.get('summary', '')}")

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

            # ---- 真实 RSI(14) 计算 ----
            rsi_value = 50.0
            rsi_div = 0  # 0=无, 1=底背离, -1=顶背离
            close_list_str = sr.get("close_list", "")
            if close_list_str:
                try:
                    closes = [float(x) for x in close_list_str.split(",") if x]
                    rsi_value = _calc_rsi(closes, 14)
                    # RSI 背离检测：比较前半段和后半段的 RSI 趋势 vs 价格趋势
                    if len(closes) >= 14:
                        mid = len(closes) // 2
                        first_half = closes[:mid]
                        second_half = closes[mid:]
                        if len(first_half) >= 5 and len(second_half) >= 5:
                            rsi_first = _calc_rsi(first_half, min(7, len(first_half) - 1))
                            rsi_second = _calc_rsi(second_half, min(7, len(second_half) - 1))
                            p_first = sum(first_half) / len(first_half)
                            p_second = sum(second_half) / len(second_half)
                            price_trend = "lower_low" if p_second < p_first * 0.98 else "higher_high" if p_second > p_first * 1.02 else "flat"
                            rsi_trend = "higher_low" if rsi_second > rsi_first + 3 else "lower_high" if rsi_second < rsi_first - 3 else "flat"
                            rsi_div = _rsi_divergence(price_trend, rsi_trend)
                except (ValueError, ZeroDivisionError, IndexError):
                    rsi_value = 50.0

            # ---- 个股策略分类（均值回归模式） ----
            # A类（突破确认）：仅当价格突破箱体上沿 + 量能配合 + RSI中性偏强
            # B类（反转埋伏）：价格回调到支撑位附近 + RSI偏低/底背离
            avg_pct = sr.get("avg_pct_5d")
            is_type_a = False
            is_type_b = False

            # A类条件更苛刻：须靠近箱体顶 + 量能放大 + RSI > 40（不是超买区）
            if (box_pos is not None and box_pos > 0.75
                    and sr.get("vol_ratio", 0) or 0 > 1.2
                    and 40 <= rsi_value <= 65):
                is_type_a = True
            # B类放宽：箱体底部附近或 RSI 偏低的都算
            if box_pos is not None and box_pos < 0.35:
                is_type_b = True
            if rsi_value < 40:
                is_type_b = True
            if avg_pct is not None and avg_pct < -2:
                is_type_b = True  # 短期超跌也算
            # RSI底背离 → B类
            if rsi_div == 1:
                is_type_a = False
                is_type_b = True
            # RSI顶背离 → 过滤
            if rsi_div == -1:
                continue

            if is_type_a:
                strategy_type = "A"
            elif is_type_b:
                strategy_type = "B"
            else:
                continue

            # ---- 动态权重分配（均值回归 + 三段式：bull/震荡/bear） ----
            # 反转市下：RSI、箱体位置权重高，趋势/突破权重低
            if market_status == "bull":
                if strategy_type == "A":
                    w1, w2, w3, w4, w5, w6 = 0.10, 0.15, 0.25, 0.10, 0.15, 0.25
                else:
                    w1, w2, w3, w4, w5, w6 = 0.05, 0.10, 0.35, 0.10, 0.05, 0.35
            elif market_status == "震荡":
                if strategy_type == "A":
                    w1, w2, w3, w4, w5, w6 = 0.05, 0.15, 0.30, 0.10, 0.10, 0.30
                else:
                    w1, w2, w3, w4, w5, w6 = 0.05, 0.10, 0.35, 0.10, 0.05, 0.35
            else:  # bear
                if strategy_type == "A":
                    w1, w2, w3, w4, w5, w6 = 0.05, 0.10, 0.35, 0.15, 0.05, 0.30
                else:
                    w1, w2, w3, w4, w5, w6 = 0.05, 0.10, 0.40, 0.10, 0.05, 0.30

            # ---- 因子评分（均值回归方向） ----
            f6 = sr.get("f6_box_volume", 0) or 0  # 箱体底部放量 → 保留，方向正确

            # f1_reversal: 短期超跌评分（0~20）
            # 近5日跌越多分越高（均值回归预期）
            if avg_pct is not None:
                if avg_pct < -3:
                    f1 = 20
                elif avg_pct < -2:
                    f1 = 16
                elif avg_pct < -1:
                    f1 = 12
                elif avg_pct < 0:
                    f1 = 8
                elif avg_pct < 2:
                    f1 = 4
                else:
                    f1 = 0  # 涨太多的不追
            else:
                f1 = 0

            # f2_vol_reversal: 缩量回调评分（0~15）
            # 回调过程中缩量 = 抛压耗尽 = 反弹潜力
            vol_ratio_val = sr.get("vol_ratio", 1.0) or 1.0
            if avg_pct is not None and avg_pct < 0 and vol_ratio_val < 0.8:
                f2 = 15  # 跌 + 缩量 = 最佳
            elif avg_pct is not None and avg_pct < 0 and vol_ratio_val < 1.0:
                f2 = 10
            elif vol_ratio_val < 0.6:
                f2 = 8  # 极度缩量
            elif vol_ratio_val > 2.0 and avg_pct is not None and avg_pct > 0:
                f2 = 3  # 放量上涨 → 追高风险
            elif vol_ratio_val > 1.5:
                f2 = 5
            else:
                f2 = 6

            # f3_rsi_reversal: 超卖反弹评分（0~25）
            # RSI越低分越高（但极端低可能继续跌，给中性分）
            if 25 <= rsi_value <= 40:
                f3 = 25  # 最佳超卖反弹区
            elif 40 < rsi_value <= 50:
                f3 = 18  # 中性偏低
            elif 15 <= rsi_value < 25:
                f3 = 14  # 深度超卖
            elif 50 < rsi_value <= 60:
                f3 = 10  # 中性
            elif 60 < rsi_value <= 70:
                f3 = 6   # 偏强
            elif rsi_value > 70:
                f3 = 3   # 超买不参与
            else:
                f3 = 10

            # f4_stability: 低波动评分（0~15）
            # 低波动 → 蓄力充分 → 容易反弹
            pct_std = sr.get("pct_std_5d")
            if pct_std and pct_std > 0:
                if pct_std < 1.0:
                    f4 = 15
                elif pct_std < 2.0:
                    f4 = 10
                elif pct_std < 3.0:
                    f4 = 5
                else:
                    f4 = 0
            else:
                f4 = 5

            # f5_reversal: 价格位置评分（0~10）
            # 靠近5日低点 = 超跌 = 反弹潜力
            close_to_high_pct = sr.get("close_to_high_pct")
            if close_to_high_pct is not None:
                if close_to_high_pct < 0.2:
                    f5 = 10  # 靠近5日低点
                elif close_to_high_pct < 0.4:
                    f5 = 7
                elif close_to_high_pct < 0.6:
                    f5 = 4
                elif close_to_high_pct > 0.9:
                    f5 = 1  # 靠近5日高点 → 追高风险
                else:
                    f5 = 3
            else:
                f5 = 0

            # ---- 量价确认（反转版） ----
            # 缩量下跌 = 抛压衰竭，加分；放量下跌 = 恐慌，中性
            vol_penalty = 1.0
            if avg_pct is not None and avg_pct < 0 and vol_ratio_val < 0.7:
                vol_penalty = 1.15  # 缩量下跌 → 加分
            elif avg_pct is not None and avg_pct < 0 and vol_ratio_val > 2.0:
                vol_penalty = 0.85  # 放量下跌 → 还有下跌动能

            # ---- RSI 调整项（反转版） ----
            rsi_adjustment = 0
            if rsi_value < 35:
                rsi_adjustment += 5  # 超卖加分
            if rsi_value > 70:
                rsi_adjustment -= 4  # 超买减分
            if rsi_div == 1:
                rsi_adjustment += 5  # 底背离大幅加分

            # ---- 龙虎榜（不变） ----
            institution_bonus = 0
            if lh.get("has_longhu"):
                inst_ratio = lh.get("institution_ratio", 0.0) or 0.0
                inst_net_buy = lh.get("institution_net_buy", 0.0) or 0.0
                if inst_ratio > 0.3 and inst_net_buy > 0:
                    institution_bonus = 4
                elif inst_ratio > 0.2 and inst_net_buy > 0:
                    institution_bonus = 2
                elif inst_ratio > 0.1 and inst_net_buy > 0:
                    institution_bonus = 1
                elif inst_ratio > 0.3 and inst_net_buy < 0:
                    institution_bonus = -2

            # ---- AI题材热度系数（不变） ----
            ai_hot_bonus = 0
            if s.get("ai_count", 1) >= 2:
                ai_hot_bonus = 8
            elif s.get("ai_count", 1) >= 1:
                ai_hot_bonus = 3

            dynamic_score = round(
                (f1 * w1 + f2 * w2 + f3 * w3 + f4 * w4 + f5 * w5 + f6 * w6
                 + lh_bonus + institution_bonus + ai_hot_bonus + rsi_adjustment) * vol_penalty, 2
            )

            final_score = dynamic_score
            
            # ============================================================
            # 关键价位 + 操作规则（基于回测优化的止损止盈参数）
            #
            # 优化依据：scripts/_optimize_stop_loss.py 模拟验证结果：
            #   TOP3 原始      : 46.4%胜率, 盈亏比 1.21
            #   TOP3 止损3%+止盈5%: 46.0%胜率, 盈亏比 1.35（累计收益+47%）
            #
            # A型(突破): 止损-3% 止盈+5% 持有≤5天 — 突破失败跑得快
            # B型(埋伏): 止损-5% 止盈+8% 持有≤5天 — 给底部震荡留空间
            # ============================================================
            close = sr["latest_close"]
            if close is None or close == 0:
                buy_final = sell_final = stop_final = None
                stop_loss_pct = take_profit_pct = 0
                hold_days = 5
            elif strategy_type == "A":
                # A型：突破型 — 严格止损，快速止盈
                buy_final = round(close * 0.99, 2)
                stop_final = round(close * 0.97, 2)   # -3%
                sell_final = round(close * 1.05, 2)   # +5%
                stop_loss_pct = 3
                take_profit_pct = 5
                hold_days = 5
            else:
                # B型：埋伏型 — 宽止损，高止盈
                buy_final = round(close * 0.99, 2)
                stop_final = round(close * 0.95, 2)   # -5%
                sell_final = round(close * 1.08, 2)   # +8%
                stop_loss_pct = 5
                take_profit_pct = 8
                hold_days = 5
            
            # 构建评分说明（每个因子一行）
            score_detail_parts = []
            score_detail_parts.append(f"趋势:{f1}×{w1:.2f}={round(f1*w1,1)}")
            score_detail_parts.append(f"量价:{f2}×{w2:.2f}={round(f2*w2,1)}")
            score_detail_parts.append(f"RSI:{f3}×{w3:.2f}={round(f3*w3,1)}")
            score_detail_parts.append(f"稳定:{f4}×{w4:.2f}={round(f4*w4,1)}")
            score_detail_parts.append(f"突破:{f5}×{w5:.2f}={round(f5*w5,1)}")
            score_detail_parts.append(f"箱体:{f6}×{w6:.2f}={round(f6*w6,1)}")
            if rsi_adjustment:
                score_detail_parts.append(f"RSI调:{rsi_adjustment:+.0f}")
            if vol_penalty != 1.0:
                score_detail_parts.append(f"量价折:×{vol_penalty}")
            if lh_bonus:
                score_detail_parts.append(f"龙虎榜:{lh_bonus}")
            if institution_bonus:
                score_detail_parts.append(f"机构:{institution_bonus}")
            if ai_hot_bonus:
                score_detail_parts.append(f"AI热度:{ai_hot_bonus}")
            score_detail = "\n".join(score_detail_parts) + f"\n总分={final_score}"
            # 追加操作指南
            score_detail += (
                f"\n操作: 买入≤{buy_final} "
                f"止损{stop_loss_pct}%({stop_final}) "
                f"止盈{take_profit_pct}%({sell_final}) "
                f"持有≤{hold_days}天"
            )

            result.append({
                "code": code,
                "name": sr["name"],
                "sector": s.get("sector", ""),
                "reason": s.get("reason", ""),
                "avg_pct_5d": sr["avg_pct_5d"],
                "avg_amp_5d": sr["avg_amp_5d"],
                "vol_ratio": sr["vol_ratio"],
                "latest_close": close,
                "rsi_value": round(rsi_value, 1),
                "rsi_divergence": rsi_div,
                "score": final_score,
                "score_detail": score_detail,
                "strategy_type": strategy_type,
                "market_status": market_status,
                "longhu_net_buy": lh.get("net_buy", 0),
                "longhu_bonus": lh_bonus,
                "institution_ratio": lh.get("institution_ratio", 0.0),
                "institution_bonus": institution_bonus,
                "ai_hot_bonus": ai_hot_bonus,
                # 操作规则（回测优化）
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "hold_days": hold_days,
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
                "rsi_value": None,
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
                "stop_loss_pct": 0,
                "take_profit_pct": 0,
                "hold_days": 5,
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
