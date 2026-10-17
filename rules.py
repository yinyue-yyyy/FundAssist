"""Deterministic, announcement-parameterized calculations. No model calls."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from models import AnnouncementFacts, Kind, RuleResult, UserScenario


def decimal_value(value: str | None, label: str, *, positive: bool = False) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        number = Decimal(value.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"{label}请输入数字，不要包含单位。") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0) or number > Decimal("1e15"):
        raise ValueError(f"{label}必须为{'正数' if positive else '非负数'}，且不超过 10^15。")
    if max(0, -number.as_tuple().exponent) > 6:
        raise ValueError(f"{label}最多保留 6 位小数。")
    return number


def parse_date(value: str | None, label: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}请使用 YYYY-MM-DD 格式。") from exc


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def evaluate_rules(facts: AnnouncementFacts, scenario: UserScenario) -> RuleResult:
    result = RuleResult()
    # Validate even fields not used in this particular branch; never silently ignore bad inputs.
    for field in ("purchase_amount", "recurring_amount", "transfer_amount", "holding_shares"):
        decimal_value(getattr(scenario, field), field)
    if scenario.change_requested_at:
        try:
            datetime.fromisoformat(scenario.change_requested_at)
        except ValueError as exc:
            raise ValueError("变更申请时间请使用 YYYY-MM-DD HH:MM 格式。") from exc
    for field in ("announcement_date", "departure_date", "limit_start", "record_date", "ex_date", "payment_date"):
        parse_date(facts.get(field), field)
    if facts.conflicts:
        result.needs_check.extend(f"公告信息存在冲突：{s}" for s in facts.conflicts)
    result.needs_check.extend(facts.missing)

    if facts.kind == Kind.MANAGER:
        for key, label in (("manager_leaving", "离任基金经理"), ("manager_remaining", "继续管理的基金经理"),
                           ("departure_reason", "公告所载离任原因"), ("departure_date", "离任日期")):
            value = facts.get(key)
            if value:
                result.confirmed.append(f"{label}：{value}。")
                result.used_fact_keys.append(key)
            else:
                result.needs_check.append(f"公告中未确认{label}。")
        result.confirmed.append("公告不能证明离任与产品表现有关，也不能据此判断基金后续一定下跌或上涨。")
        result.needs_check.append("如需进一步解释离任背景，应核实基金管理人正式说明，不能编造原因或业绩判断。")
    elif facts.kind == Kind.LIMIT:
        _limit(facts, scenario, result)
    elif facts.kind == Kind.DIVIDEND:
        _dividend(facts, scenario, result)
    else:
        result.needs_check.append("当前版本仅支持基金经理变更、大额申购限制、基金分红三类公告。")
    result.needs_check = list(dict.fromkeys(result.needs_check))
    return result


def _limit(facts: AnnouncementFacts, s: UserScenario, r: RuleResult) -> None:
    start = parse_date(facts.get("limit_start"), "限制起始日")
    limit = decimal_value(facts.get("aggregate_limit"), "合并限额", positive=True)
    fields = ("purchase_amount", "recurring_amount", "transfer_amount")
    values = [decimal_value(getattr(s, f), f) for f in fields]
    total = sum((v for v in values if v is not None), Decimal(0))
    r.used_fact_keys.extend(["limit_start", "aggregate_limit", "aggregate_scope", "limit_exclusive",
                             "limit_account_scope", "rejection_policy", "resume_date"])
    if any(v is not None for v in values):
        r.calculations["known_daily_total"] = money(total)
        r.confirmed.append(f"已提供的同日申购、定投、转换转入金额合计为 {money(total)} 元。")
    else:
        r.needs_check.append("请补充同一账户、同一执行日的申请金额。")
    if any(v is None for v in values):
        r.needs_check.append("尚有同日业务金额未知；已提供金额仅构成已知合计，需核实其他申请。")
    if not s.execution_date:
        r.needs_check.append("请核实定投实际扣款／申请执行日，月度计划金额不能替代实际执行日期。")
    active = start is not None and s.execution_date is not None and s.execution_date >= start
    before = start is not None and s.execution_date is not None and s.execution_date < start
    if start:
        r.confirmed.append(f"本公告限制起始日为 {start.isoformat()}。")
    else:
        r.needs_check.append("限制起始日尚未确认。")
    scope = facts.get("aggregate_scope")
    account_scope = facts.get("limit_account_scope")
    if not scope or not account_scope or limit is None:
        r.needs_check.append("需确认合并限额、合并业务及单日单账户适用口径，暂不能完成限额判断。")
    elif any(v is not None for v in values):
        r.calculations["aggregate_limit"] = money(limit)
        exclusive = facts.get("limit_exclusive")
        if exclusive not in ("是", "否"):
            r.needs_check.append("公告的限额是否包含边界尚未确认。")
        else:
            exceeds = total > limit if exclusive == "是" else total >= limit
            detail = f"已知合计 {money(total)} 元{'触及' if exceeds else '未触及'}公告的 {money(limit)} 元限制条件"
            if before:
                r.confirmed.append("该执行日在本公告限制起始日之前，本公告尚未生效；仍需核实当日其他适用规则。")
            elif exceeds:
                text = detail + "；管理人可能拒绝相关申请，不能据此认定自动降额、部分成交或已扣款失败。"
                if active:
                    r.conditional.append(text)
                else:
                    r.conditional.append("如果执行日在限制生效后，" + text)
            elif all(v is not None for v in values) and active:
                r.confirmed.append(detail + "；仅代表未触及本条限额，不保证申请最终成功。")
            else:
                r.conditional.append(detail + "；须确认执行日期及其他同日申请后，才能判断实际影响。")
    if facts.get("resume_date"):
        r.confirmed.append("恢复安排：" + facts.get("resume_date") + "。")
    else:
        r.needs_check.append("恢复时间未明确，应关注基金管理人后续正式公告，不能推测日期。")
    if facts.get("unaffected_business"):
        r.confirmed.append("公告说明其他业务安排：" + facts.get("unaffected_business") + "。")
    r.needs_check.append("核实销售机构的扣款、受理和拒绝处理结果；公告未说明 A/C 类合并口径时，不自行补充。")


def _dividend(facts: AnnouncementFacts, s: UserScenario, r: RuleResult) -> None:
    shares = decimal_value(s.holding_shares, "持有份额")
    amount = decimal_value(facts.get("dividend_per"), "每组分红金额")
    base = decimal_value(facts.get("dividend_base"), "分红对应份额", positive=True)
    r.used_fact_keys.extend(["dividend_per", "dividend_base", "record_date", "payment_date",
                             "method_effective_rule", "method_change_rule", "reinvest_basis", "eligibility_rule"])
    if shares is not None and amount is not None and base is not None:
        dividend = shares / base * amount
        r.calculations["dividend_amount"] = money(dividend)
        r.calculations["dividend_formula"] = f"{shares:f} ÷ {base:f} × {amount:f} = {money(dividend)} 元"
        if s.eligible_shares is True:
            r.confirmed.append(f"按已确认符合本次分红资格的 {shares:f} 份计算，分红金额为 {money(dividend)} 元。")
        elif s.eligible_shares is False:
            r.calculations.pop("dividend_amount")
            r.calculations.pop("dividend_formula")
            r.needs_check.append("所填份额未确认具备本次分红资格，不能作为实际应得分红金额。")
        else:
            r.conditional.append(f"如果 {shares:f} 份均符合本次分红资格，分红金额为 {money(dividend)} 元。")
            r.needs_check.append("请确认权益登记日在册及申购、赎回／转换申请对分红资格的影响。")
    else:
        r.needs_check.append("需补充具备分红资格的份额数，以及公告中的分红金额与对应份额数。")
    if s.registry_verified and s.registry_method:
        method = "现金分红" if s.registry_method == "cash" else "红利再投资"
        r.confirmed.append(f"根据运营人员已核实的本次适用登记记录，分红方式为{method}。")
    else:
        if s.original_method:
            original = "现金分红" if s.original_method == "cash" else "红利再投资"
            r.confirmed.append(f"用户补充的原分红方式为{original}；它不等于本次最终适用的登记结果。")
        r.needs_check.append("现金还是基金份额，须以本次权益登记日前最后一次有效选择及注册登记机构记录核实。")
        if facts.get("default_method"):
            r.conditional.append(f"未有效选择分红方式时，公告／产品资料所列默认为{facts.get('default_method')}；不能直接认定该用户采用默认方式。")
    if s.change_requested_at:
        r.confirmed.append(f"用户称在 {s.change_requested_at}（中国当地时间）提交分红方式变更申请。")
        r.needs_check.append("申请时间不等于生效时间；核查销售机构受理规则、回执和登记结果，不能仅凭 16:00 或常见截止时间判定有效／无效。")
    if not (s.registry_verified and s.registry_method == "cash"):
        r.conditional.append("如本次有效方式为红利再投资，将依据公告所述除息后净值确定份额；未提供该净值，不能计算具体再投资份额。")
    if facts.get("payment_date"):
        r.confirmed.append(f"公告现金红利发放日为 {facts.get('payment_date')}；这不等于用户账户实际到账日。")
    if facts.get("record_date"):
        r.confirmed.append(f"权益登记日为 {facts.get('record_date')}。")
