"""Small, shared data contracts. Model schemas deliberately contain no business defaults."""
from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Kind(StrEnum):
    MANAGER = "manager_change"
    LIMIT = "purchase_limit"
    DIVIDEND = "dividend"
    OTHER = "unsupported"


KIND_LABELS = {
    Kind.MANAGER: "基金经理变更", Kind.LIMIT: "大额申购限制",
    Kind.DIVIDEND: "基金分红", Kind.OTHER: "暂不支持的公告类型",
}

# Stable keys shared by prompts, fact editor, rules and exports.
FIELD_LABELS = {
    "fund_name": "基金名称", "fund_code": "基金主代码",
    "announcement_date": "公告送出日期", "manager_leaving": "离任基金经理",
    "manager_remaining": "继续管理的基金经理", "departure_reason": "离任原因",
    "departure_date": "离任日期", "limit_start": "限制起始日",
    "purchase_limit": "申购限额（元）", "recurring_limit": "定投限额（元）",
    "transfer_limit": "转换转入限额（元）", "aggregate_limit": "合并限额（元）",
    "aggregate_scope": "合并业务口径", "limit_exclusive": "超过限额才触及限制（是/否）",
    "limit_account_scope": "账户及时间口径", "rejection_policy": "超额处理方式",
    "unaffected_business": "不受影响的业务", "resume_date": "恢复日期或安排",
    "record_date": "权益登记日", "ex_date": "除息日",
    "payment_date": "现金红利发放日", "dividend_per": "分红金额（元）",
    "dividend_base": "上述金额对应的份额数", "default_method": "默认分红方式",
    "method_effective_rule": "分红方式生效依据", "method_change_rule": "变更方式办理规则",
    "reinvest_basis": "红利再投资份额计算依据", "reinvest_confirm_date": "再投资份额确认日",
    "reinvest_query_date": "再投资份额可查询日", "eligibility_rule": "分红权益规则",
    "payment_definition": "发放日含义",
}
NUMERIC_FIELDS = {
    "purchase_limit", "recurring_limit", "transfer_limit", "aggregate_limit",
    "dividend_per", "dividend_base",
}
DATE_FIELDS = {
    "announcement_date", "departure_date", "limit_start", "record_date", "ex_date",
    "payment_date", "reinvest_confirm_date", "reinvest_query_date",
}
COMMON_FIELDS = {"fund_name", "fund_code", "announcement_date"}
KIND_FIELDS = {
    Kind.MANAGER: COMMON_FIELDS | {"manager_leaving", "manager_remaining", "departure_reason", "departure_date"},
    Kind.LIMIT: COMMON_FIELDS | {"limit_start", "purchase_limit", "recurring_limit", "transfer_limit",
        "aggregate_limit", "aggregate_scope", "limit_exclusive", "limit_account_scope", "rejection_policy",
        "unaffected_business", "resume_date"},
    Kind.DIVIDEND: COMMON_FIELDS | {"record_date", "ex_date", "payment_date", "dividend_per", "dividend_base",
        "default_method", "method_effective_rule", "method_change_rule", "reinvest_basis",
        "reinvest_confirm_date", "reinvest_query_date", "eligibility_rule", "payment_definition"},
    Kind.OTHER: COMMON_FIELDS,
}


class SourcePage(StrictModel):
    source_id: str
    page: int = Field(ge=1)
    text: str
    label: str
    is_original: bool = True


class Citation(StrictModel):
    source_id: str
    page: int
    quote: str


class Fact(StrictModel):
    key: str
    value: str | None
    origin: Literal["announcement", "product", "manual"]
    citations: list[Citation]

    @field_validator("key")
    @classmethod
    def known_key(cls, value: str) -> str:
        if value not in FIELD_LABELS:
            raise ValueError(f"未知事实字段：{value}")
        return value


class AnnouncementFacts(StrictModel):
    kind: Kind
    facts: list[Fact]
    missing: list[str]
    conflicts: list[str]

    def get(self, key: str) -> str | None:
        return next((f.value for f in self.facts if f.key == key), None)


class UserScenario(StrictModel):
    question: str = Field(max_length=3000)
    purchase_amount: str | None = None
    recurring_amount: str | None = None
    transfer_amount: str | None = None
    execution_date: date | None = None
    holding_shares: str | None = None
    eligible_shares: bool | None = None
    original_method: Literal["cash", "reinvest"] | None = None
    change_requested_at: str | None = None
    registry_method: Literal["cash", "reinvest"] | None = None
    registry_verified: bool = False


class RuleResult(StrictModel):
    confirmed: list[str] = Field(default_factory=list)
    conditional: list[str] = Field(default_factory=list)
    needs_check: list[str] = Field(default_factory=list)
    calculations: dict[str, str] = Field(default_factory=dict)
    used_fact_keys: list[str] = Field(default_factory=list)


class FAQ(StrictModel):
    question: str
    answer: str

    @field_validator("question", "answer", mode="before")
    @classmethod
    def normalize_line_breaks(cls, value):
        return value.replace("\\n", "\n") if isinstance(value, str) else value


class MaterialDraft(StrictModel):
    summary: str
    customer_reply: str
    faqs: list[FAQ]
    app_title: str
    app_body: str
    internal_checks: list[str]
    referenced_fact_keys: list[str]

    @field_validator("summary", "customer_reply", "app_title", "app_body", mode="before")
    @classmethod
    def normalize_line_breaks(cls, value):
        return value.replace("\\n", "\n") if isinstance(value, str) else value


class RunRecord(StrictModel):
    request_id: str
    stage: str
    timestamp: str
    model: str
    prompt_version: str
    input_hash: str
    status: str
    elapsed_seconds: float
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_usd: str | None = None
    error_code: str | None = None
    response_id: str | None = None
    reused: bool = False
    model_output_text: str | None = None
    validation_notes: list[str] = Field(default_factory=list)
