"""Generate a weekly market narrative via Claude Haiku.

Called on Fridays after the daily report. Sends the structured weekly summary
to claude-haiku-4-5 and asks it to write a concise Portuguese debrief.
Graceful: returns an empty string on any failure so the weekly email still
sends without the narrative paragraph.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 600   # narrative capped at ~1200 chars ≈ 300-350 tokens; headroom for safety

_SYSTEM = (
    "Você é um analista sênior de mercados financeiros. "
    "Escreva um resumo semanal conciso e perspicaz em português brasileiro. "
    "Tom conversacional, como um debrief de sexta à tarde entre colegas. "
    "Máximo 1200 caracteres totais. Sem markdown, sem bullet points — apenas parágrafos."
)

_INSTRUCTION_TEMPLATE = """\
Com base nos dados abaixo, escreva exatamente 3-4 parágrafos curtos em português:

• Parágrafo 1: como evoluiu o contexto macro esta semana (Fear & Greed, Buffett)
• Parágrafo 2: padrões dominantes (ex.: "metais preciosos mostraram atividade institucional persistente a semana toda")
• Parágrafo 3: os sinais de maior destaque e o que podem indicar
• Parágrafo 4: o que observar na próxima semana

---
{summary_text}
"""


def _build_summary_text(summary: dict) -> str:
    """Flatten the structured summary into a compact prompt body."""
    days = summary.get("days_analyzed", 0)
    total = summary.get("total_signals", 0)
    red = summary.get("red_alerts", [])
    amber = summary.get("amber_alerts", [])
    freq = summary.get("asset_frequency", {})
    highest_vol = summary.get("highest_volume", [])
    me = summary.get("macro_evolution", {})

    fg_start = (me.get("fear_greed_start") or {}).get("score", "N/A")
    fg_end = (me.get("fear_greed_end") or {}).get("score", "N/A")
    buf_start_pct = (me.get("buffett_start") or {}).get("pct", "N/A")
    buf_start_cls = (me.get("buffett_start") or {}).get("class", "")
    buf_end_pct = (me.get("buffett_end") or {}).get("pct", "N/A")
    buf_end_cls = (me.get("buffett_end") or {}).get("class", "")

    top_assets = list(freq.items())[:6]

    lines = [
        f"Semana: {summary.get('week_start')} a {summary.get('week_end')}",
        f"Dias analisados: {days} de 5 dias úteis",
        f"Total de alertas: {total} ({len(red)} RED, {len(amber)} AMBER)",
        "",
        f"Ativos mais frequentes: {', '.join(f'{t} ({d}d)' for t, d in top_assets) or 'nenhum'}",
        "",
        "Maiores picos de volume da semana:",
    ]
    for v in highest_vol:
        lines.append(f"  {v['ticker']} em {v['date']}: {v['ratio']:.1f}x")
    if not highest_vol:
        lines.append("  (sem dados)")

    lines += [
        "",
        "Evolução macro:",
        f"  Fear & Greed: início {fg_start}/100 → fim {fg_end}/100",
        f"  Buffett: início {buf_start_pct}% ({buf_start_cls}) → fim {buf_end_pct}% ({buf_end_cls})",
    ]
    return "\n".join(lines)


def generate_weekly_narrative(summary: dict, macro: dict) -> str:  # noqa: ARG001
    """Call Claude Haiku and return a Portuguese weekly briefing string.

    `macro` is accepted for interface consistency but the relevant macro data
    is already embedded in `summary["macro_evolution"]`.

    Returns an empty string on any failure (missing key, network error, etc.).
    """
    if not summary:
        return ""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping weekly narrative")
        return ""

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — skipping weekly narrative")
        return ""

    summary_text = _build_summary_text(summary)
    user_content = _INSTRUCTION_TEMPLATE.format(summary_text=summary_text)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        narrative = response.content[0].text.strip()
        logger.info(
            f"weekly narrative generated: "
            f"input={response.usage.input_tokens} "
            f"output={response.usage.output_tokens} tokens"
        )
        return narrative
    except Exception as e:
        logger.warning(f"weekly narrative failed: {e}")
        return ""
