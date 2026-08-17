"""LLM 仲裁 prompt 模板与决策解析。"""
from __future__ import annotations

import json
import re

CONFLICT_SYSTEM_PROMPT = """\
You are the conflict-resolution advisor of a container terminal dispatching \
system. Two vessels are competing for the same berth at overlapping times. \
Given structured facts, decide which vessel should keep the berth (winner). \
Consider: vessel priority (1=highest), contractual preference, workload, \
waiting time already incurred, and operational fairness. \
You MUST answer with a single JSON object only, no extra text: \
{"winner": "<vessel_id>", "reason": "<one short sentence>"}\
"""

CONFLICT_USER_TEMPLATE = """\
Conflict context:
- berth_id: {berth_id}
- incumbent (currently planned earlier / may have started): {incumbent}
- challenger (would be delayed if losing): {challenger}
- terminal snapshot: crane shortage caused the incumbent's service time to \
be extended beyond the planned completion, overlapping the challenger's \
berthing window.

Which vessel should keep the berth? Answer in JSON only.\
"""


def build_conflict_prompt(conflict: dict) -> str:
    """将冲突场景结构化为用户 prompt。"""
    vessels = conflict.get("vessels", [])
    incumbent = next(
        (v for v in vessels if v.get("role") == "incumbent"), vessels[0] if vessels else {})
    challenger = next(
        (v for v in vessels if v.get("role") == "challenger"), vessels[-1] if vessels else {})
    return CONFLICT_USER_TEMPLATE.format(
        berth_id=conflict.get("berth_id", "?"),
        incumbent=json.dumps(incumbent, ensure_ascii=False),
        challenger=json.dumps(challenger, ensure_ascii=False),
    )


def parse_llm_decision(text: str | None, valid_ids: list[str]) -> dict | None:
    """解析 LLM 输出 {"winner": ..., "reason": ...}；失败或非法返回 None。"""
    if not text:
        return None
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    winner = str(data.get("winner", ""))
    if winner not in valid_ids:
        return None
    return {"winner": winner, "reason": str(data.get("reason", ""))[:200]}
