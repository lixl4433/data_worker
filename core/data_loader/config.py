"""
数据加载模块配置
"""
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)

START_DATE = "20250101"
def get_today() -> str:
    """动态获取当前日期 YYYYMMDD，确保每次调用都是最新日期"""
    return __import__("datetime").datetime.now().strftime("%Y%m%d")
SQL_BATCH_SIZE = 500

# Pytdx IP 列表（统一从 config.py 导入）
from config import PYTDX_CONFIGS
PYTDX_IPS = [(cfg["ip"], cfg["port"]) for cfg in PYTDX_CONFIGS]
