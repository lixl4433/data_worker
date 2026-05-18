"""
热点新闻采集模块 - 从多个新闻/社交媒体平台获取当下热点词条

支持的来源：
  1. 抖音热搜
  2. 微博热搜
  3. 东方财富要闻
  4. 同花顺热榜
  5. 华尔街见闻
"""

import re
import json
import time
import logging
from typing import Optional
from datetime import datetime

import httpx
from openai import OpenAI

logger = logging.getLogger("hot_news")

# ---------------------------------------------------------------------------
# 代理配置（复用 ai_analyzer 中的代理检测逻辑）
# ---------------------------------------------------------------------------
_COMMON_PROXY_PORTS = [7897, 7890, 10809, 10808, 1080, 8080]


def _get_proxy() -> Optional[str]:
    """检测系统代理"""
    import os
    import socket

    for var in ["HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"]:
        proxy = os.environ.get(var, "").strip()
        if proxy:
            return proxy

    for port in _COMMON_PROXY_PORTS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            if result == 0:
                return f"http://127.0.0.1:{port}"
        except Exception:
            continue
    return None


def _create_client(timeout: int = 15) -> httpx.Client:
    """创建带代理的 httpx 客户端"""
    proxy = _get_proxy()
    if proxy:
        return httpx.Client(proxy=proxy, timeout=timeout, follow_redirects=True)
    return httpx.Client(timeout=timeout, follow_redirects=True)


# ===================================================================
# 各平台采集函数
# ===================================================================

def fetch_douyin_hot() -> list:
    """采集抖音热搜"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://www.douyin.com/aweme/v1/web/hot/search/list/",
                params={"detail_list": 1, "source": 6},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.douyin.com/",
                },
            )
            data = resp.json()
            for item in data.get("data", {}).get("word_list", []):
                items.append({
                    "title": item.get("word", ""),
                    "hot_value": item.get("hot_value", 0),
                    "source": "抖音热搜",
                })
    except Exception as e:
        logger.warning(f"抖音热搜采集失败: {e}")
    return items


def fetch_weibo_hot() -> list:
    """采集微博热搜"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://weibo.com/ajax/side/hotSearch",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://weibo.com/",
                },
            )
            data = resp.json()
            for item in data.get("data", {}).get("realtime", []):
                items.append({
                    "title": item.get("word", ""),
                    "hot_value": item.get("raw_hot", 0),
                    "source": "微博热搜",
                })
    except Exception as e:
        logger.warning(f"微博热搜采集失败: {e}")
    return items


def fetch_baidu_hot() -> list:
    """采集百度热搜"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://top.baidu.com/board?tab=realtime",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            # 从 HTML 中提取 JSON 数据
            html = resp.text
            # 百度热搜数据在 <script> 标签中的 window.__INITIAL_STATE__
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                cards = data.get("data", {}).get("cards", [])
                for card in cards:
                    for item in card.get("content", []):
                        items.append({
                            "title": item.get("word", item.get("query", "")),
                            "hot_value": item.get("hotScore", 0),
                            "source": "百度热搜",
                        })
    except Exception as e:
        logger.warning(f"百度热搜采集失败: {e}")
    return items


def fetch_zhihu_hot() -> list:
    """采集知乎热榜"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.zhihu.com/",
                },
            )
            data = resp.json()
            for item in data.get("data", []):
                target = item.get("target", {})
                title = target.get("title", "")
                if not title:
                    title = target.get("question", {}).get("title", "")
                items.append({
                    "title": title,
                    "hot_value": item.get("detail_text", ""),
                    "source": "知乎热榜",
                })
    except Exception as e:
        logger.warning(f"知乎热榜采集失败: {e}")
    return items


def fetch_eastmoney_hot() -> list:
    """采集东方财富要闻（头条）"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://finance.eastmoney.com/yaowen.html",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://www.eastmoney.com/index.html",
                },
            )
            html = resp.text
            # 提取 artitleList2 中的头条新闻
            match = re.search(
                r'<div class="artitleList2"[^>]*id="artitileList1"[^>]*>(.*?)</div>\s*</div>\s*</div>',
                html, re.DOTALL
            )
            if match:
                content = match.group(1)
                links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', content)
                for url, title in links[:20]:
                    title = title.strip()
                    if title and len(title) > 5 and '更多' not in title:
                        items.append({
                            "title": title,
                            "hot_value": "",
                            "source": "东方财富要闻",
                        })
    except Exception as e:
        logger.warning(f"东方财富要闻采集失败: {e}")
    return items


def fetch_ths_hot() -> list:
    """采集同花顺热榜（使用同花顺热搜 API）"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/topic?page=1&page_size=30",
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://eq.10jqka.com.cn",
                    "Referer": "https://eq.10jqka.com.cn/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            data = resp.json()
            for item in data.get("data", {}).get("topic_list", []):
                title = item.get("title", "")
                subtitle = item.get("subtitle", "")
                hot_value = item.get("hot_value", 0)
                description = item.get("description", "")
                # 标题 + 副标题
                display_title = title
                if subtitle:
                    display_title = f"{title} - {subtitle}"
                items.append({
                    "title": display_title,
                    "hot_value": hot_value,
                    "source": "同花顺热榜",
                    "description": description,
                })
    except Exception as e:
        logger.warning(f"同花顺热榜采集失败: {e}")
    return items




def fetch_cls_hot() -> list:
    """采集财联社头条（top_article）"""
    items = []
    try:
        with _create_client() as client:
            # 先访问首页获取 Cookie
            client.get(
                "https://www.cls.cn/depth?id=1000",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            # 再请求 API
            resp = client.get(
                "https://www.cls.cn/v3/depth/home/assembled/1000?app=CailianpressWeb&os=web&sv=8.4.6",
                headers={
                    "accept": "application/json, text/plain, */*",
                    "referer": "https://www.cls.cn/depth?id=1000",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            data = resp.json()
            articles = data.get("data", {}).get("top_article", [])
            for a in articles[:10]:
                title = a.get("title", "")
                if title:
                    items.append({
                        "title": title,
                        "hot_value": "",
                        "source": "财联社",
                    })
    except Exception as e:
        logger.warning(f"财联社采集失败: {e}")
    return items


def fetch_wallstreetcn_hot() -> list:
    """采集华尔街见闻快讯-要闻（只看重要）"""
    items = []
    try:
        with _create_client() as client:
            # 华尔街见闻快讯 API
            resp = client.get(
                "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=30",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://wallstreetcn.com/",
                },
            )
            data = resp.json()
            for item in data.get("data", {}).get("items", []):
                title = item.get("title", "") or item.get("content_text", "")
                # 只看重要（display_style = 1 或 display_time 不为空）
                is_important = item.get("display_style") == 1 or item.get("display_time") is not None
                if title and is_important:
                    items.append({
                        "title": title.strip(),
                        "hot_value": item.get("display_time", ""),
                        "source": "华尔街见闻",
                    })
            if not items:
                # 如果 API 没返回重要标记，取前 10 条
                for item in data.get("data", {}).get("items", [])[:10]:
                    title = item.get("title", "") or item.get("content_text", "")
                    if title:
                        items.append({
                            "title": title.strip(),
                            "hot_value": "",
                            "source": "华尔街见闻",
                        })
    except Exception as e:
        logger.warning(f"华尔街见闻采集失败: {e}")
    return items


def fetch_sina_finance_hot() -> list:
    """采集新浪财经热点"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://feed.mix.sina.com.cn/api/roll/get",
                params={
                    "pageid": 153,
                    "lid": 2509,
                    "k": "",
                    "num": 30,
                    "page": 1,
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            data = resp.json()
            for item in data.get("result", {}).get("data", []):
                items.append({
                    "title": item.get("title", ""),
                    "hot_value": item.get("ctime", ""),
                    "source": "新浪财经",
                })
    except Exception as e:
        logger.warning(f"新浪财经采集失败: {e}")
    return items


def fetch_tencent_news_hot() -> list:
    """采集腾讯新闻热点"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://news.qq.com/",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
            )
            html = resp.text
            # 从 HTML 中提取新闻标题
            titles = re.findall(r'<a[^>]*title="(.*?)"', html)
            for title in titles[:30]:
                if title.strip():
                    items.append({
                        "title": title.strip(),
                        "hot_value": "",
                        "source": "腾讯新闻",
                    })
    except Exception as e:
        logger.warning(f"腾讯新闻采集失败: {e}")
    return items


def fetch_36kr_hot() -> list:
    """采集36氪热点"""
    items = []
    try:
        with _create_client() as client:
            resp = client.get(
                "https://36kr.com/newsflashes",
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://36kr.com/",
                },
            )
            html = resp.text
            # 36氪数据在 <script> 中的 window.__INITIAL_STATE__
            match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', html, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                news_data = data.get("newsflashList", {}).get("data", {}).get("itemList", [])
                for item in news_data:
                    items.append({
                        "title": item.get("title", ""),
                        "hot_value": item.get("readCount", 0),
                        "source": "36氪",
                    })
    except Exception as e:
        logger.warning(f"36氪采集失败: {e}")
    return items


# ===================================================================
# 统一采集入口
# ===================================================================

# 所有采集函数列表
_SOURCES = [
    ("抖音热搜", fetch_douyin_hot),
    ("微博热搜", fetch_weibo_hot),
    ("东方财富要闻", fetch_eastmoney_hot),
    ("同花顺热榜", fetch_ths_hot),
    ("华尔街见闻", fetch_wallstreetcn_hot),
]


def collect_all_hot_news(timeout_per_source: int = 10) -> dict:
    """
    采集所有来源的热点新闻。

    Args:
        timeout_per_source: 每个来源的超时时间（秒）

    Returns:
        dict: {
            "sources": { "抖音热搜": [...], "微博热搜": [...], ... },
            "all_news": [...],  # 所有新闻合并列表
            "timestamp": "...",
            "total_count": int,
        }
    """
    result = {
        "sources": {},
        "all_news": [],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_count": 0,
    }

    total = 0
    for name, fetch_func in _SOURCES:
        try:
            logger.info(f"正在采集 {name}...")
            items = fetch_func()
            if items:
                result["sources"][name] = items
                result["all_news"].extend(items)
                total += len(items)
                logger.info(f"  {name}: {len(items)} 条")
            else:
                logger.warning(f"  {name}: 无数据")
        except Exception as e:
            logger.error(f"  {name} 采集异常: {e}")

    result["total_count"] = total
    logger.info(f"采集完成，共 {total} 条热点新闻")
    return result


def get_hot_keywords(top_n: int = 50) -> list:
    """
    获取热点关键词（去重后按热度排序）。

    Args:
        top_n: 返回前 N 个关键词

    Returns:
        list: [{"keyword": "...", "sources": [...], "count": int}, ...]
    """
    data = collect_all_hot_news()
    keyword_map = {}

    for source_name, items in data["sources"].items():
        for item in items:
            title = item.get("title", "").strip()
            if not title:
                continue
            # 简单分词：按标点、空格分割，取有意义的词
            words = re.split(r'[，。！？、；：""''（）\(\)\[\]【】\s/\\|]', title)
            for word in words:
                word = word.strip()
                # 过滤太短或无意义的词
                if len(word) < 2:
                    continue
                if word not in keyword_map:
                    keyword_map[word] = {
                        "keyword": word,
                        "sources": set(),
                        "count": 0,
                    }
                keyword_map[word]["sources"].add(source_name)
                keyword_map[word]["count"] += 1

    # 按出现次数排序
    sorted_keywords = sorted(
        keyword_map.values(),
        key=lambda x: (-x["count"], x["keyword"]),
    )

    # 转换为可序列化格式
    result = []
    for kw in sorted_keywords[:top_n]:
        result.append({
            "keyword": kw["keyword"],
            "sources": list(kw["sources"]),
            "count": kw["count"],
        })

    return result


# ===================================================================
# DeepSeek 热点新闻聚合分析
# ===================================================================

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL


def analyze_hot_news_with_deepseek(raw_text: str) -> str:
    """
    调用 DeepSeek 对原始热点新闻进行聚合分析，返回精简的聚合结果。

    Args:
        raw_text: 原始榜单文本（含来源和标题）

    Returns:
        str: 聚合后的文本，每行格式 "[权重：X次] 聚合语义标题"
    """
    prompt = f"""你是一个专业的热点新闻聚合分析助手。

【输入】
用户会提供5个榜单（按影响力从高到低排列）：
- 华尔街见闻（专业财经媒体，权重最高）
- 东方财富要闻（专业财经媒体，权重高）
- 同花顺热榜（专业财经媒体，权重高）
- 微博热搜（综合社交平台，权重中）
- 抖音热搜（泛娱乐平台，权重低）

{raw_text}

【处理步骤】

1. 信源权重分级
   - 华尔街见闻、东方财富、同花顺的新闻：视为高权重信源，优先保留
   - 微博热搜：中等权重，只保留与财经/科技/产业相关的条目
   - 抖音热搜：低权重，只保留重大时政/财经/科技事件，过滤泛娱乐内容

2. 过滤规则（优先执行）
   - 过滤掉明显广告、营销、抽奖、晒图、个人生活分享
   - 过滤掉娱乐八卦、无实质新闻价值的段子或梗
   - 过滤掉纯个人情绪表达或"家族第一个打开XX"等无公共意义内容
   - 只保留：时政、财经、科技、产业、国际关系、社会民生、重大事件

3. 识别新闻阶段（关键）
   对每条有效新闻，判断其处于哪个阶段：
   - 【发酵期】事件刚出现，讨论度在上升，尚未被市场充分定价 → 最有价值
   - 【爆发期】事件已广泛传播，股价已有反应，处于主升浪 → 中等价值
   - 【衰退期】事件已过时，热度在下降，股价可能已见顶 → 低价值或过滤
   
   在输出时，对【发酵期】的新闻给予更高权重，对【衰退期】的新闻降权或过滤。

4. 语义精简
   对每条有效词条：
   - 提取核心语义（10~20字以内）
   - 去除冗余修饰词、主观情绪词
   - 保留主谓宾、关键实体（公司/人名/产品/事件）
   - 不同榜单中同一事件，精简为一致表达

5. 跨榜单聚合
   - 将所有精简词条按语义合并为事件组
   - 每组生成一个最终"聚合语义标题"（一句话概括）
   - 同一事件在多个榜单中出现才需要合并；单榜单独立事件保留但权重低

6. 加权排序
   - 权重 = 该事件出现在不同榜单中的总次数（同一榜单内重复不计）
   - 同次数时，按信源权重排序：华尔街见闻/东财/同花顺 > 微博 > 抖音
   - 同次数同信源时，【发酵期】事件排在【爆发期】前面，【衰退期】排最后

7. 输出格式（严格按此格式，不要添加任何额外内容）
[权重：X次] 聚合语义标题
[权重：X次] 聚合语义标题
……

【重要】
- 不要编造不存在的事件
- 不要合并语义明显不同的事件
- 不要输出序号、来源、原文示例、过滤说明、任何解释性文字
- 只输出上述格式的行，每行一条"""

    try:
        proxy = _get_proxy()
        client_kwargs = {"timeout": 60}
        if proxy:
            client_kwargs["http_client"] = httpx.Client(proxy=proxy, timeout=60)

        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            **client_kwargs,
        )

        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的热点新闻聚合分析助手，严格按用户要求的格式输出。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )

        result = resp.choices[0].message.content.strip()
        logger.info(f"DeepSeek 热点聚合完成，输出 {len(result.split(chr(10)))} 行")
        return result

    except Exception as e:
        logger.error(f"DeepSeek 热点聚合分析失败: {e}")
        return ""


# ===================================================================
# 主入口
# ===================================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("=" * 60)
    print("热点新闻采集")
    print("=" * 60)

    result = collect_all_hot_news()

    print(f"\n采集时间: {result['timestamp']}")
    print(f"总条数: {result['total_count']}")
    print()

    for source_name, items in result["sources"].items():
        print(f"\n--- {source_name} ({len(items)} 条) ---")
        for i, item in enumerate(items[:10], 1):
            hot = f" (热度: {item['hot_value']})" if item.get("hot_value") else ""
            print(f"  {i}. {item['title']}{hot}")
        if len(items) > 10:
            print(f"  ... 共 {len(items)} 条")

    print("\n" + "=" * 60)
    print("热点关键词 TOP 30")
    print("=" * 60)
    keywords = get_hot_keywords(30)
    for i, kw in enumerate(keywords, 1):
        print(f"  {i}. {kw['keyword']} (出现 {kw['count']} 次, 来源: {', '.join(kw['sources'])})")
