"""
微信推送 API
"""
import sqlite3
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Form

from web.config import get_conn, dict_from_row, logger
from config import PUSHPLUS_TOKEN

router = APIRouter(tags=["微信推送"])


async def send_wx_push(title: str, content: str) -> bool:
    """通过 PushPlus 推送消息到微信"""
    if not PUSHPLUS_TOKEN:
        logger.warning("未配置 PUSHPLUS_TOKEN，无法推送微信消息")
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": PUSHPLUS_TOKEN,
                    "title": title,
                    "content": content,
                    "template": "markdown",
                },
                headers={"Content-Type": "application/json"},
            )
            result = resp.json()
            if result.get("code") == 200:
                logger.info("微信推送成功")
                return True
            else:
                logger.warning(f"微信推送失败: {result}")
                return False
    except Exception as e:
        logger.warning(f"微信推送异常: {e}")
        return False


def format_stocks_for_push(stocks: list, title: str) -> str:
    """将股票列表格式化为 Markdown 推送内容"""
    if not stocks:
        return f"**{title}**\n\n暂无数据"
    lines = [f"# {title}", ""]
    lines.append(f"共 **{len(stocks)}** 只股票")
    lines.append("")
    lines.append("| 排名 | 代码 | 名称 | 评分 |")
    lines.append("|------|------|------|------|")
    for s in stocks[:20]:
        score = s.get("total_score") or s.get("score") or 0
        lines.append(f"| {s.get('rank', '-')} | {s.get('code', '-')} | {s.get('name', '-')} | {score} |")
    if len(stocks) > 20:
        lines.append(f"\n... 共 {len(stocks)} 只，仅展示前 20 只")
    return "\n".join(lines)


@router.get("/api/wx-push")
async def api_wx_push_list():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, wx_id, remark, created_at FROM wx_push ORDER BY id DESC")
    items = [dict_from_row(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": items}


@router.post("/api/wx-push")
async def api_add_wx_push(wx_id: str = Form(...), remark: str = Form("")):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO wx_push (wx_id, remark) VALUES (?, ?)", (wx_id, remark))
        conn.commit()
        return {"code": 0, "message": "添加成功"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="该微信号已存在")
    finally:
        conn.close()


@router.delete("/api/wx-push/{push_id}")
async def api_delete_wx_push(push_id: int):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM wx_push WHERE id = ?", (push_id,))
    conn.commit()
    conn.close()
    return {"code": 0, "message": "删除成功"}
