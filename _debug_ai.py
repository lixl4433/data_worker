"""临时调试脚本：查看 DeepSeek 原始返回"""
import sys, json, logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)

from core.ai_analyzer import call_deepseek, parse_stock_response
from openai import OpenAI
import httpx

# 直接调用 API 看原始返回
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

# 检测代理
from core.ai_analyzer import _get_proxy
proxy = _get_proxy()
client_kwargs = {"timeout": 120}
if proxy:
    client_kwargs["http_client"] = httpx.Client(proxy=proxy, timeout=120)

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
    **client_kwargs,
)

print("=" * 60)
print("调用 DeepSeek API...")
print("=" * 60)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "你是一个专业的量化策略分析师，请严格按照要求的 JSON 格式输出。"},
        {"role": "user", "content": "请输出一个简单的 JSON 示例：{\"themes\": [{\"theme_rank\": 1, \"theme_name\": \"测试题材\", \"stage\": \"发酵期\", \"core_drivers\": \"测试\", \"stocks\": [{\"rank\": 1, \"code\": \"600519\", \"name\": \"贵州茅台\", \"reason\": \"测试\"}]}]}"},
    ],
    temperature=0.7,
    max_tokens=4096,
)

text = response.choices[0].message.content.strip()
print(f"\n原始返回长度: {len(text)} 字符")
print(f"\n原始返回内容前 200 字符:")
print(repr(text[:200]))
print(f"\n原始返回内容后 200 字符:")
print(repr(text[-200:]))

# 尝试解析
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

# 方法3: 正则匹配 themes
json_match = re.search(r'\{.*"themes".*\}', text, re.DOTALL)
if json_match:
    try:
        data = json.loads(json_match.group(0))
        print("方法3 (正则themes): 成功")
    except json.JSONDecodeError as e:
        print(f"方法3 (正则themes): 失败 - {e}")
else:
    print("方法3 (正则themes): 未匹配到")

# 方法4: 正则匹配 stocks
json_match = re.search(r'\{.*"stocks".*\}', text, re.DOTALL)
if json_match:
    try:
        data = json.loads(json_match.group(0))
        print("方法4 (正则stocks): 成功")
    except json.JSONDecodeError as e:
        print(f"方法4 (正则stocks): 失败 - {e}")
else:
    print("方法4 (正则stocks): 未匹配到")

# 最终用 parse_stock_response
print("\n" + "=" * 60)
print("调用 parse_stock_response:")
stocks = parse_stock_response(text)
if stocks:
    print(f"解析成功: {len(stocks)} 只股票")
else:
    print("解析失败")
