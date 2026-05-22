"""
核心配置模块 - 自动化选股系统

Windows / Linux 通用版本（无需 GPU / CUDA / PyTorch）

所有 API Key / Token 统一在此管理，各模块通过 from config import xxx 引用。
"""

import os
import sys
import sqlite3
from pathlib import Path


# ============================================================
# 项目路径
# ============================================================

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"

# 数据库路径
DB_PATH = DATA_DIR / "quant_storage.db"


# ============================================================
# AI 大模型 API 配置
# ============================================================

# DeepSeek
DEEPSEEK_API_KEY = "sk-d42dc2f9174d4ac7b2fe8b69a53b7e6b"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Kimi（月之暗面）
KIMI_API_KEY = "sk-QggnDxp2SrrEIvhE0jcgrJu8YaAx234YHq1Qt7MJkjsGbntR"
KIMI_BASE_URL = "https://api.moonshot.cn/v1"

# Gemini（Google） - 手动导入模式，无需配置 API Key
# Grok（xAI） - 手动导入模式，无需配置 API Key
# ChatGPT（OpenAI） - 手动导入模式，无需配置 API Key


# ============================================================
# A 股数据接口配置
# ============================================================

# TuShare Pro Token（用于获取历史行情）
TUSHARE_TOKEN = "6299df56e14a99ca5f31c5d4ee81d508b94e72b73501aaf80e923aca"

# Pytdx 配置（直连券商行情站）
# 多个备用 IP，连接失败自动切换
PYTDX_CONFIGS = [
    {"ip": "119.147.212.81", "port": 7709, "name": "招商证券"},   # 常用
    {"ip": "119.147.212.81", "port": 7709, "name": "招商证券2"},   # 同IP不同端口
    {"ip": "218.75.126.9",   "port": 7709, "name": "华泰证券"},    # 备用
    {"ip": "180.153.18.170", "port": 7709, "name": "东方财富"},    # 备用
    {"ip": "119.147.212.81", "port": 7710, "name": "招商证券(7710)"}, # 备用端口
]
PYTDX_TIMEOUT = 10


# ============================================================
# 微信推送配置
# ============================================================

# PushPlus Token（用于微信推送选股结果）
# 留空则不推送
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")


# ============================================================
# 数据库工具函数
# ============================================================


def get_db_path() -> Path:
    """获取数据库路径"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DB_PATH


def get_db_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    db_path = get_db_path()
    print(f"[config] 初始化完成，数据库路径: {db_path}")
