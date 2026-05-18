"""
提示词管理 API
"""
import logging

from fastapi import APIRouter, Form

from web.config import get_conn, dict_from_row, logger

router = APIRouter(tags=["提示词管理"])


@router.get("/api/prompt-templates")
async def api_prompt_templates():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, is_default, created_at, updated_at FROM prompt_templates ORDER BY id")
    items = [dict_from_row(row) for row in cursor.fetchall()]
    conn.close()
    return {"code": 0, "data": items}


@router.get("/api/prompt-templates/{template_id}")
async def api_prompt_template_detail(template_id: int):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM prompt_templates WHERE id = ?", (template_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"code": -1, "message": "模板不存在"}
    return {"code": 0, "data": dict_from_row(row)}


@router.get("/api/prompt-templates/active/content")
async def api_prompt_active_content():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM prompt_templates WHERE name = '最新版本'")
    row = cursor.fetchone()
    if row:
        conn.close()
        return {"code": 0, "data": {"content": row["content"]}}
    cursor.execute("SELECT content FROM prompt_templates WHERE is_default = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"code": 0, "data": {"content": row["content"]}}
    return {"code": -1, "message": "无提示词模板"}


@router.post("/api/prompt-templates/save")
async def api_prompt_template_save(name: str = Form(...), content: str = Form(...)):
    conn = get_conn()
    cursor = conn.cursor()
    try:
        if name == "最新版本":
            cursor.execute(
                "UPDATE prompt_templates SET content = ?, updated_at = datetime('now', 'localtime') WHERE name = '最新版本'",
                (content,))
            if cursor.rowcount == 0:
                cursor.execute(
                    "INSERT INTO prompt_templates (name, content, is_default) VALUES ('最新版本', ?, 0)", (content,))
            conn.commit()
            return {"code": 0, "message": "最新版本已更新"}
        else:
            cursor.execute(
                "INSERT INTO prompt_templates (name, content, is_default) VALUES (?, ?, 0)", (name, content))
            conn.commit()
            return {"code": 0, "message": f"模板「{name}」已创建"}
    except Exception as e:
        return {"code": -1, "message": f"保存失败: {str(e)}"}
    finally:
        conn.close()


@router.post("/api/prompt-templates/reset-default")
async def api_prompt_template_reset_default():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM prompt_templates WHERE is_default = 1")
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"code": -1, "message": "无默认版本"}
    cursor.execute(
        "UPDATE prompt_templates SET content = ?, updated_at = datetime('now', 'localtime') WHERE name = '最新版本'",
        (row["content"],))
    conn.commit()
    conn.close()
    return {"code": 0, "message": "已还原为默认版本"}


@router.post("/api/prompt-templates/set-as-default")
async def api_prompt_template_set_as_default():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM prompt_templates WHERE name = '最新版本'")
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"code": -1, "message": "无最新版本"}
    cursor.execute(
        "UPDATE prompt_templates SET content = ?, updated_at = datetime('now', 'localtime') WHERE is_default = 1",
        (row["content"],))
    conn.commit()
    conn.close()
    return {"code": 0, "message": "最新版本已设为默认版本"}
