"""Fundamental / valuation screener — A-share stock value assessment.

PE, PB, ROE, growth, debt, dividend — all scored 0-100.
"""

import logging
from typing import Any

from stockpicker.schemas import FundamentalScore

logger = logging.getLogger("stockpicker.value")


def score_fundamental(
    fundamentals: dict[str, Any] | None = None,
) -> FundamentalScore:
    """
    Score A-share stock fundamental / valuation.

    Input dict can contain:
        pe_ttm, pb, roe, revenue_growth_pct, profit_growth_pct,
        debt_to_asset_pct, dividend_yield_pct, market_cap
    """
    if not fundamentals:
        return FundamentalScore(
            total=50, summary="无基本面数据，默认中性50分"
        )

    pe = fundamentals.get("pe_ttm")
    pb = fundamentals.get("pb")
    roe = fundamentals.get("roe")
    rev_g = fundamentals.get("revenue_growth_pct")
    profit_g = fundamentals.get("profit_growth_pct")
    debt = fundamentals.get("debt_to_asset_pct")
    div_yield = fundamentals.get("dividend_yield_pct")
    market_cap = fundamentals.get("market_cap", 0)

    reasons: list[str] = []

    # ── PE score (0-100) ──
    pe_score = 50.0
    if pe is not None:
        if pe <= 0:  # 亏损
            pe_score = 20
            reasons.append(f"PE={pe:.1f} 亏损")
        elif pe <= 15:
            pe_score = 85
            reasons.append(f"PE={pe:.1f} 低估")
        elif pe <= 25:
            pe_score = 70
            reasons.append(f"PE={pe:.1f} 合理偏低")
        elif pe <= 40:
            pe_score = 50
            reasons.append(f"PE={pe:.1f} 合理偏高")
        elif pe <= 60:
            pe_score = 30
            reasons.append(f"PE={pe:.1f} 偏高")
        else:
            pe_score = 15
            reasons.append(f"PE={pe:.1f} 严重高估")
    else:
        reasons.append("PE数据缺失")

    # ── PB score ──
    pb_score = 50.0
    if pb is not None:
        if pb <= 0:
            pb_score = 15
        elif pb <= 1:
            pb_score = 80
            reasons.append(f"PB={pb:.2f} 破净")
        elif pb <= 3:
            pb_score = 65
        elif pb <= 5:
            pb_score = 45
        elif pb <= 10:
            pb_score = 30
        else:
            pb_score = 15

    # ── ROE score ──
    roe_score = 50.0
    if roe is not None:
        if roe > 20:
            roe_score = 90
            reasons.append(f"ROE={roe:.1f}% 优秀")
        elif roe > 15:
            roe_score = 75
            reasons.append(f"ROE={roe:.1f}% 良好")
        elif roe > 8:
            roe_score = 55
        elif roe > 0:
            roe_score = 35
        else:
            roe_score = 15
            reasons.append(f"ROE={roe:.1f}% 亏损")

    # ── Growth score ──
    growth_score = 50.0
    if profit_g is not None:
        if profit_g > 50:
            growth_score = 90
            reasons.append(f"利润增长{profit_g:.0f}% 高速")
        elif profit_g > 20:
            growth_score = 75
            reasons.append(f"利润增长{profit_g:.0f}% 良好")
        elif profit_g > 0:
            growth_score = 55
        elif profit_g > -20:
            growth_score = 30
            reasons.append(f"利润下滑{profit_g:.0f}%")
        else:
            growth_score = 10
            reasons.append(f"利润大幅下滑{profit_g:.0f}%")
    elif rev_g is not None:
        if rev_g > 30:
            growth_score = 75
        elif rev_g > 10:
            growth_score = 60
        elif rev_g > 0:
            growth_score = 45
        else:
            growth_score = 25

    # ── Debt score ──
    debt_score = 50.0
    if debt is not None:
        if debt < 20:
            debt_score = 85
            reasons.append(f"负债率{debt:.0f}% 极低")
        elif debt < 40:
            debt_score = 70
        elif debt < 60:
            debt_score = 50
        elif debt < 80:
            debt_score = 30
            reasons.append(f"负债率{debt:.0f}% 偏高")
        else:
            debt_score = 10
            reasons.append(f"负债率{debt:.0f}% 极高")

    # ── Dividend score ──
    div_score = 50.0
    if div_yield is not None:
        if div_yield > 5:
            div_score = 90
            reasons.append(f"股息率{div_yield:.2f}% 优秀")
        elif div_yield > 3:
            div_score = 75
        elif div_yield > 1:
            div_score = 55
        elif div_yield > 0:
            div_score = 35
        else:
            div_score = 15

    # ── Weighted total ──
    total = (
        pe_score * 0.20 +
        pb_score * 0.10 +
        roe_score * 0.25 +
        growth_score * 0.20 +
        debt_score * 0.15 +
        div_score * 0.10
    )

    summary = "; ".join(reasons) if reasons else "基本面数据中性"
    return FundamentalScore(
        pe_score=round(pe_score, 1),
        pb_score=round(pb_score, 1),
        roe_score=round(roe_score, 1),
        growth_score=round(growth_score, 1),
        debt_score=round(debt_score, 1),
        dividend_score=round(div_score, 1),
        total=round(total, 1),
        summary=summary,
    )
