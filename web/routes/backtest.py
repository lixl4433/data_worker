"""
回测 API - 基于综合评分的历史回测
"""
from fastapi import APIRouter, Request
from web.config import logger
from core.backtest import run_backtest

router = APIRouter(tags=["回测"])


@router.get("/api/backtest")
async def api_backtest(
    date_from: str = "",
    date_to: str = "",
    top_n: int = 5,
    hold_days: int = 5,
    strategy_type: str = "",
    min_score: float = 0,
):
    """运行综合评分回测"""
    result = run_backtest(
        date_from=date_from,
        date_to=date_to,
        top_n=top_n,
        hold_days=hold_days,
        strategy_type=strategy_type,
        min_score=min_score,
    )
    return result
