"""
AI 选股 API（5 模型：DeepSeek/Kimi 自动 + Gemini/Grok/ChatGPT 手动导入）
"""
import json
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Form, Request

from web.config import get_conn, dict_from_row, logger
from core.ai_analyzer import run_ai_analysis

router = APIRouter(tags=["AI 选股"])

# 缓存最新的 AI 分析结果
_ai_analysis_cache = {}

# 手动导入的数据存储
_manual_import_cache = {"gemini": None, "grok": None, "chatgpt": None}


def save_ai_picks_to_db(model: str, stocks: list):
    """将某个模型的选股结果保存到 ai_picks 表"""
    if not stocks:
        return
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ai_picks WHERE model = ?", (model,))

        themes_data = None
        flat_stocks = []

        if isinstance(stocks, dict) and "themes" in stocks:
            themes_data = stocks["themes"]
            for theme in themes_data:
                theme_name = theme.get("theme_name", "")
                stage = theme.get("stage", "")
                core_drivers = theme.get("core_drivers", "")
                for s in theme.get("stocks", []):
                    reason = s.get("reason", "")
                    if core_drivers:
                        reason = f"[{theme_name}][{stage}] {core_drivers} | {reason}"
                    flat_stocks.append({
                        "code": s.get("code", ""), "name": s.get("name", ""),
                        "sector": theme_name, "reason": reason, "rank": s.get("rank", 0),
                    })
        elif isinstance(stocks, list) and len(stocks) > 0:
            first = stocks[0]
            if isinstance(first, dict) and "theme_name" in first and "stocks" in first:
                themes_data = stocks
                for theme in themes_data:
                    theme_name = theme.get("theme_name", "")
                    stage = theme.get("stage", "")
                    core_drivers = theme.get("core_drivers", "")
                    for s in theme.get("stocks", []):
                        reason = s.get("reason", "")
                        if core_drivers:
                            reason = f"[{theme_name}][{stage}] {core_drivers} | {reason}"
                        flat_stocks.append({
                            "code": s.get("code", ""), "name": s.get("name", ""),
                            "sector": theme_name, "reason": reason, "rank": s.get("rank", 0),
                        })
            else:
                flat_stocks = stocks

        if themes_data:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ai_picks_raw (
                    model TEXT NOT NULL, raw_data TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (model)
                )
            """)
            cursor.execute(
                "INSERT OR REPLACE INTO ai_picks_raw (model, raw_data) VALUES (?, ?)",
                (model, json.dumps(themes_data, ensure_ascii=False))
            )

        for s in flat_stocks:
            cursor.execute(
                "INSERT OR REPLACE INTO ai_picks (model, code, name, sector, reason, rank) VALUES (?, ?, ?, ?, ?, ?)",
                (model, s.get("code", ""), s.get("name", ""),
                 s.get("sector", ""), s.get("reason", ""), s.get("rank", 0))
            )
        conn.commit()
        logger.info(f"AI 选股结果已持久化: model={model}, count={len(flat_stocks)}")
    except Exception as e:
        logger.error(f"保存 AI 选股结果失败: model={model}, error={e}")
    finally:
        conn.close()


def load_ai_picks_from_db():
    """启动时从 ai_picks 表加载所有模型的选股结果"""
    global _ai_analysis_cache
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT model FROM ai_picks ORDER BY model")
        models = [row["model"] for row in cursor.fetchall()]
        if not models:
            conn.close()
            return
        cache = {}
        for model in models:
            cursor.execute(
                "SELECT code, name, sector, reason, rank FROM ai_picks WHERE model = ? ORDER BY rank",
                (model,)
            )
            cache[model] = [dict(row) for row in cursor.fetchall()]
        _ai_analysis_cache = cache
        _ai_analysis_cache["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.close()
        logger.info(f"AI 选股缓存加载完成，共 {len(models)} 个模型")
    except Exception as e:
        logger.error(f"加载 AI 选股缓存失败: {e}")


@router.post("/api/ai-analyze")
async def api_ai_analyze():
    """调用 DeepSeek 和 Kimi 进行 AI 分析"""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_ai_analysis)

        global _ai_analysis_cache
        for model_name in ["gemini", "grok", "chatgpt"]:
            manual_data = _manual_import_cache.get(model_name)
            if manual_data:
                result[model_name] = manual_data

        _ai_analysis_cache = result
        for model_name in _manual_import_cache:
            _manual_import_cache[model_name] = None

        for model_name in ["deepseek", "kimi", "gemini", "grok", "chatgpt", "merged", "scored"]:
            stocks = result.get(model_name, [])
            if stocks:
                save_ai_picks_to_db(model_name, stocks)

        return {
            "code": 0, "message": "AI 分析完成",
            "data": {
                "deepseek_count": len(result.get("deepseek", [])),
                "kimi_count": len(result.get("kimi", [])),
                "gemini_count": len(result.get("gemini", [])),
                "grok_count": len(result.get("grok", [])),
                "chatgpt_count": len(result.get("chatgpt", [])),
                "merged_count": len(result.get("merged", [])),
                "scored_count": len(result.get("scored", [])),
                "timestamp": result.get("timestamp", ""),
            },
        }
    except Exception as e:
        logger.error(f"AI 分析异常: {e}")
        return {"code": -1, "message": f"AI 分析失败: {str(e)}"}


@router.post("/api/ai-import")
async def api_ai_import(model: str = Form(...), json_data: str = Form(...)):
    """手动导入某个模型的 JSON 数据"""
    if model not in _manual_import_cache:
        return {"code": -1, "message": f"不支持的模型: {model}"}
    try:
        data = json.loads(json_data)
        stocks = None
        themes = None

        if "themes" in data and isinstance(data["themes"], list):
            themes = data["themes"]
            stocks = []
            for theme in themes:
                theme_name = theme.get("theme_name", "")
                for s in theme.get("stocks", []):
                    stocks.append({
                        "code": str(s.get("code", "")).strip(),
                        "name": str(s.get("name", "")).strip(),
                        "sector": theme_name,
                        "reason": str(s.get("reason", "")).strip(),
                    })
        elif "stocks" in data and isinstance(data["stocks"], list):
            stocks = data["stocks"]
        else:
            return {"code": -1, "message": "JSON 格式错误：需要 stocks 数组或 themes 数组"}

        if not stocks:
            return {"code": -1, "message": "股票列表为空"}

        validated = []
        for i, s in enumerate(stocks, 1):
            if not s.get("code") or not s.get("name"):
                return {"code": -1, "message": f"股票数据格式错误：缺少 code 或 name"}
            validated.append({
                "rank": i,
                "code": str(s.get("code", "")).strip(),
                "name": str(s.get("name", "")).strip(),
                "sector": str(s.get("sector", "")).strip(),
                "reason": str(s.get("reason", "")).strip(),
            })

        _manual_import_cache[model] = validated
        global _ai_analysis_cache
        if _ai_analysis_cache:
            _ai_analysis_cache[model] = validated

        if themes:
            save_ai_picks_to_db(model, {"themes": themes})
        else:
            save_ai_picks_to_db(model, validated)

        return {"code": 0, "message": f"{model} 数据导入成功，共 {len(validated)} 只股票", "count": len(validated)}
    except json.JSONDecodeError as e:
        return {"code": -1, "message": f"JSON 解析失败: {str(e)}"}
    except Exception as e:
        logger.error(f"导入 {model} 异常: {e}")
        return {"code": -1, "message": f"导入失败: {str(e)}"}


@router.get("/api/ai-stock-picks")
async def api_ai_stock_picks(source: str = "scored"):
    """获取 AI 分析结果"""
    global _ai_analysis_cache
    if not _ai_analysis_cache:
        return {"code": 0, "data": [], "total": 0, "source": source}

    source_map = {
        "scored": "scored", "deepseek": "deepseek", "kimi": "kimi",
        "gemini": "gemini", "grok": "grok", "chatgpt": "chatgpt", "merged": "merged",
    }
    key = source_map.get(source, "merged")
    stocks = _ai_analysis_cache.get(key, [])

    if source in ("deepseek", "kimi"):
        try:
            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT raw_data FROM ai_picks_raw WHERE model = ?", (source,))
            row = cursor.fetchone()
            conn.close()
            if row:
                raw_themes = json.loads(row["raw_data"])
                if raw_themes and isinstance(raw_themes, list):
                    return {
                        "code": 0, "data": raw_themes, "total": len(raw_themes),
                        "source": source, "format": "themes",
                        "timestamp": _ai_analysis_cache.get("timestamp", ""),
                    }
        except Exception:
            pass

    return {
        "code": 0, "data": stocks, "total": len(stocks),
        "source": source, "format": "flat",
        "timestamp": _ai_analysis_cache.get("timestamp", ""),
    }


@router.post("/api/ai-score-batch")
async def api_ai_score_batch(request: Request):
    """批量评分接口"""
    try:
        body = await request.json()
        stocks = body.get("stocks", [])
        if not stocks:
            return {"code": -1, "message": "股票列表为空"}

        from core.ai_analyzer import score_ai_stocks
        input_stocks = [{
            "code": s.get("code", ""), "name": s.get("name", ""),
            "sector": s.get("sector", ""), "reason": s.get("reason", ""),
        } for s in stocks]

        scored = score_ai_stocks(input_stocks)

        sources_map = {}
        weight_map = {}
        for s in stocks:
            code = s.get("code", "")
            if code:
                sources_map[code] = s.get("sources", [s.get("source", "")])
                weight_map[code] = s.get("weight", 1.0)

        for s in scored:
            code = s["code"]
            if code in sources_map:
                s["sources"] = sources_map[code]
                s["count"] = len(sources_map[code])
                weight = weight_map.get(code, 1.0)
                if weight < 1.0 and s.get("score", 0) > -9999:
                    s["score"] = round(s["score"] * weight, 2)
            else:
                s["sources"] = []
                s["count"] = 1

        scored.sort(key=lambda x: (-x.get("score", -9999), x["code"]))
        for i, item in enumerate(scored, 1):
            item["rank"] = i

        return {"code": 0, "data": scored}
    except Exception as e:
        logger.error(f"批量评分异常: {e}")
        return {"code": -1, "message": f"评分失败: {str(e)}"}
