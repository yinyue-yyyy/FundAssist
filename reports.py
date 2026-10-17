"""Exports exactly the visible, edited draft. Exporting never calls the model."""
from __future__ import annotations

import json

from models import (AnnouncementFacts, FIELD_LABELS, KIND_LABELS, MaterialDraft,
                    RuleResult, RunRecord, UserScenario)


def material_markdown(facts: AnnouncementFacts, scenario: UserScenario, rules: RuleResult,
                      draft: MaterialDraft, *, reviewed: bool, stale: bool = False) -> str:
    status = "已过期，请重新生成" if stale else ("已人工核对" if reviewed else "待人工核对")
    lines = ["# 基金公告运营材料", "", f"类型：{KIND_LABELS[facts.kind]} ｜ 状态：{status}",
             "", "> 虚构考试材料，仅供 Demo。审核标记代表当前操作人员确认，不代表外部审批。",
             "", "## 用户情境", "", scenario.question, "", "## 关键结论", "", draft.summary]
    for title, items in (("程序确认", rules.confirmed), ("条件性判断", rules.conditional),
                         ("待核实事项（内部）", rules.needs_check)):
        lines += ["", f"## {title}", ""] + ([f"- {s}" for s in items] or ["无"])
    if rules.calculations:
        lines += ["", "## 程序计算", ""] + [f"- {k}：{v}" for k, v in rules.calculations.items()]
    lines += ["", "## 客服回复", "", draft.customer_reply, "", "## 常见问答", ""]
    for faq in draft.faqs:
        lines += [f"### {faq.question}", "", faq.answer, ""]
    lines += ["## App 通知", "", f"### {draft.app_title}", "", draft.app_body,
              "", "## 内部核查清单", ""] + [f"- {s}" for s in draft.internal_checks]
    lines += ["", "## 事实与依据", ""]
    for f in facts.facts:
        if f.value is None:
            continue
        origin = {"manual": "人工补充", "product": "产品资料", "announcement": "公告／所选文本"}[f.origin]
        lines.append(f"- {FIELD_LABELS[f.key]}：{f.value}（{origin}）")
        for cite in f.citations:
            lines.append(f"  - 来源 {cite.source_id}，页／段 {cite.page}：{cite.quote}")
    return "\n".join(lines) + "\n"


def records_json(records: list[RunRecord], **context) -> str:
    return json.dumps({"is_real_model_run": True, "records": [r.model_dump() for r in records],
                       **context}, ensure_ascii=False, indent=2, default=str)
