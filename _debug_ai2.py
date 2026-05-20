"""调试脚本2：用真实热点新闻调用 DeepSeek，看原始返回"""
import sys, json, logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)

from core.ai_analyzer import _get_proxy, _get_active_prompt, parse_stock_response
from openai import OpenAI
import httpx
from datetime import datetime

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

# 1. 先采集热点新闻
print("=" * 60)
print("采集热点新闻...")
print("=" * 60)
from core.hot_news import collect_all_hot_news, analyze_hot_news_with_deepseek

news = collect_all_hot_news()
lines = []
for source_name, items in news["sources"].items():
    lines.append(f"【{source_name}】")
    for i, item in enumerate(items[:10], 1):
        title = item.get("title", "")
        hot = f" (热度: {item['hot_value']})" if item.get("hot_value") else ""
        lines.append(f"  {i}. {title}{hot}")
    lines.append("")

raw_text = "\n".join(lines)
print(f"原始热点文本长度: {len(raw_text)} 字符")

# 2. 构建提示词
prompt = _get_active_prompt()
today_str = datetime.now().strftime("%Y-%m-%d")
user_content = prompt.replace("{date}", today_str)
user_content = user_content.replace("{hot_news}", raw_text if raw_text else "无热点新闻数据")
print(f"提示词长度: {len(user_content)} 字符")

# 3. 调用 DeepSeek
print("\n" + "=" * 60)
print("调用 DeepSeek API...")
print("=" * 60)

proxy = _get_proxy()
client_kwargs = {"timeout": 120}
if proxy:
    client_kwargs["http_client"] = httpx.Client(proxy=proxy, timeout=120)

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    **client_kwargs,
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "你是一个专业的量化策略分析师，请严格按照要求的 JSON 格式输出。"},
        {"role": "user", "content": user_content},
    ],
    temperature=0.7,
    max_tokens=4096,
)

text = response.choices[0].message.content.strip()
print(f"\n原始返回长度: {len(text)} 字符")
print(f"\n=== 原始返回内容（完整）===")
print(text)
print(f"\n=== 原始返回结束 ===")

# 4. 尝试解析
print("\n" + "=" * 60)
print("尝试解析...")
print("=" * 60)

# 方法1: 直接 json.loads
try:
    data = json.loads(text)
    print("方法1 (直接json.loads): 成功")
    if "themes" in data:
        print(f"  themes 数量: {len(data['themes'])}")
        for t in data['themes']:
            print(f"  - {t['theme_name']}: {len(t.get('stocks', []))} 只股票")
except json.JSONDecodeError as e:
    print(f"方法1 (直接json.loads): 失败 - {e}")
    # 打印出错位置附近的文本
    pos = e.pos
    print(f"  出错位置: {pos}")
    print(f"  附近文本: {repr(text[max(0,pos-50):pos+50])}")

# 方法2: markdown 代码块
import re
json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
if json_match:
    try:
        data = json.loads(json_match.group(1))
        print("方法2 (markdown代码块): 成功")
    except json.JSONDecodeError as e:
        print(f"方法2 (markdown代码块): 失败 - {e}")
else:
    print("方法2 (markdown代码块): 未找到代码块")

# 最终用 parse_stock_response
print("\n" + "=" * 60)
print("调用 parse_stock_response:")
stocks = parse_stock_response(text)
if stocks:
    print(f"解析成功: {len(stocks)} 只股票")
    for s in stocks[:3]:
        print(json.dumps(s, ensure_ascii=False, indent=2))
else:
    print("解析失败")
