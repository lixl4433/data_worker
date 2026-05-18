"""
龙虎榜 API
"""
import asyncio
import json
import logging

from fastapi import APIRouter

from web.config import logger

router = APIRouter(tags=["龙虎榜"])


@router.post("/api/update-longhu")
async def api_update_longhu():
    try:
        from core.longhu import update_longhu
        result = await asyncio.to_thread(update_longhu)
        return result
    except Exception as e:
        logger.error(f"更新龙虎榜失败: {e}")
        return {"code": -1, "message": f"更新失败: {str(e)}"}


@router.get("/api/longhu")
async def api_get_longhu(date_key: str = ""):
    """获取龙虎榜数据，指定日期则从 longhu 表直接读取（含 net_buy_ratio），否则取最新"""
    try:
        from core.longhu import get_latest_longhu
        import sqlite3
        from core.longhu import _get_db_path
        
        if date_key:
            # 直接从 longhu 表读取（含 net_buy_ratio）
            conn = sqlite3.connect(str(_get_db_path()))
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("""
                SELECT code, name, trade_date, board_type, reason,
                       total_buy, total_sell, net_buy, net_buy_ratio
                FROM longhu
                WHERE trade_date = ?
                ORDER BY net_buy DESC
            """, (date_key,))
            data = [dict(r) for r in c.fetchall()]
            conn.close()
        else:
            data = get_latest_longhu(50)
        
        # 尝试从 longhu_cache 中获取 DeepSeek 原始数据
        deepseek_raw = None
        try:
            conn = sqlite3.connect(str(_get_db_path()))
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT content FROM longhu_cache WHERE date_key = ?", (date_key or (data[0]["trade_date"] if data else ""),))
            row = c.fetchone()
            if row:
                cache_content = json.loads(row["content"])
                # 检查是否有 deepseek_raw 字段
                if isinstance(cache_content, dict) and "deepseek_raw" in cache_content:
                    deepseek_raw = cache_content["deepseek_raw"]
            conn.close()
        except Exception:
            pass
        
        return {"code": 0, "data": data, "deepseek_raw": deepseek_raw}
    except Exception as e:
        logger.error(f"获取龙虎榜失败: {e}")
        return {"code": -1, "message": f"获取失败: {str(e)}"}


@router.get("/api/longhu-dates")
async def api_list_longhu_dates():
    """获取所有有龙虎榜缓存的日期列表"""
    try:
        from core.longhu import list_longhu_dates
        dates = list_longhu_dates()
        return {"code": 0, "data": dates}
    except Exception as e:
        logger.error(f"获取龙虎榜日期列表失败: {e}")
        return {"code": -1, "message": f"获取失败: {str(e)}"}
