"""FundAssist: one-page Streamlit application; run with python -m streamlit run app.py."""
from __future__ import annotations

from copy import deepcopy
from html import escape
import hmac
import json

import streamlit as st

from ai_service import PipelineError, extract_facts, generate_materials
from cases import get_case, load_cases, load_case_result
from config import MODEL, PROMPT_VERSION, ROOT, load_settings
from documents import fingerprint, read_pdf, validate_sources
from models import (AnnouncementFacts, DATE_FIELDS, FIELD_LABELS, NUMERIC_FIELDS,
                    Fact, Kind, KIND_LABELS, MaterialDraft, SourcePage, UserScenario)
from reports import material_markdown, records_json
from rules import decimal_value, evaluate_rules, parse_date
from ui import apply_styles, render_header, render_overview, render_sidebar, section_heading


st.set_page_config(page_title="基金公告运营助手", page_icon="◈", layout="wide")
apply_styles()


def invalidate_review() -> None:
    st.session_state["reviewed"] = False


def reset_document() -> None:
    for key in ("facts", "rules", "draft", "generated_facts", "generated_scenario",
                "generated_rules", "material_input_hash", "fact_kind", "fact_editor", "saved_result_path"):
        st.session_state.pop(key, None)
    st.session_state["reviewed"] = False
    st.session_state["scenario_saved"] = False
    st.session_state["fact_revision"] = 0
    st.session_state["facts_confirmed"] = False


def set_scenario(s: UserScenario) -> None:
    values = {
        "question": s.question, "purchase": s.purchase_amount or "", "recurring": s.recurring_amount or "",
        "transfer": s.transfer_amount or "", "execution": s.execution_date.isoformat() if s.execution_date else "",
        "shares": s.holding_shares or "", "eligible": "已确认" if s.eligible_shares is True else "未知",
        "original": "未知", "change_time": s.change_requested_at or "", "registry": "未知",
        "registry_verified": False,
    }
    for key, value in values.items():
        st.session_state["scenario_" + key] = value
    st.session_state["scenario"] = s


def current_input_hash(facts: AnnouncementFacts, scenario: UserScenario) -> str:
    return fingerprint({"facts": facts.model_dump(), "scenario": scenario.model_dump(mode="json"),
                        "source": st.session_state.get("active_source_hash"),
                        "model": MODEL, "prompt_version": PROMPT_VERSION})


def restore_case_result(key: str, source_hash: str) -> None:
    saved = load_case_result(key)
    if saved is None:
        return
    pages, product, _ = get_case(key)
    if source_hash != fingerprint([p.model_dump() for p in pages + product]):
        return
    s = st.session_state
    set_scenario(saved.scenario)
    cache_key = current_input_hash(saved.facts, saved.scenario)
    extraction_key = fingerprint({"source": source_hash, "model": MODEL, "prompt": PROMPT_VERSION})
    s["extraction_cache"][extraction_key] = deepcopy(saved.facts)
    s["material_cache"][cache_key] = deepcopy((saved.rules, saved.material))
    s.update(facts=deepcopy(saved.facts), rules=deepcopy(saved.rules), draft=deepcopy(saved.material),
             generated_facts=deepcopy(saved.facts), generated_scenario=deepcopy(saved.scenario),
             generated_rules=deepcopy(saved.rules), material_input_hash=cache_key,
             scenario_saved=True, reviewed=False, saved_result_path=str(saved.path.relative_to(ROOT)),
             draft_revision=s.get("draft_revision", 0) + 1)
    known_ids = {r.request_id for r in s["records"]}
    s["records"].extend(r.model_copy(update={"reused": True}, deep=True)
                       for r in saved.records if r.request_id not in known_ids)


def save_facts(rows: list[dict], kind: Kind, original: AnnouncementFacts) -> AnnouncementFacts:
    old = {f.key: f for f in original.facts}
    updated = []
    for row in rows:
        key = row["key"]
        value = str(row["值"]).strip() if row["值"] is not None else ""
        if key in NUMERIC_FIELDS:
            decimal_value(value or None, FIELD_LABELS[key], positive=key in {"dividend_base", "aggregate_limit"})
        if key in DATE_FIELDS:
            parse_date(value or None, FIELD_LABELS[key])
        if key == "limit_exclusive" and value not in ("", "是", "否"):
            raise ValueError("限额边界只能填写“是”“否”或留空。")
        prev = old.get(key)
        if prev and (prev.value or "") == value:
            updated.append(prev.model_copy(deep=True))
        elif value or prev:
            updated.append(Fact(key=key, value=value or None, origin="manual", citations=[]))
    return AnnouncementFacts(kind=kind, facts=updated, missing=original.missing, conflicts=original.conflicts)


def main() -> None:
    try:
        settings = load_settings()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    if settings.access_code and not st.session_state.get("authenticated"):
        st.markdown('<p class="eyebrow">FUNDASSIST / DEMO</p>', unsafe_allow_html=True)
        st.title("基金公告运营助手")
        with st.form("access"):
            access = st.text_input("体验码", type="password")
            enter = st.form_submit_button("进入工作台", type="primary")
        if enter:
            if hmac.compare_digest(access.encode("utf-8"), settings.access_code.encode("utf-8")):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("体验码不正确。")
        st.stop()

    for key, default in (("records", []), ("extraction_cache", {}), ("material_cache", {}),
                         ("reviewed", False), ("fact_revision", 0)):
        if key not in st.session_state:
            st.session_state[key] = default

    render_header()
    overview = st.empty()
    render_sidebar(bool(settings.api_key))
    if st.session_state.get("notice"):
        st.info(st.session_state.pop("notice"))

    with st.container(key="workspace"):
        source_tab, scenario_tab, results_tab = st.tabs(["01  公告与事实", "02  用户情境", "03  运营材料"])
    with source_tab:
        with st.container(key="import-card"):
            section_heading("01", "导入公告", "选择演示案例，或导入需要解读的公告原文。")
            mode = st.radio("材料来源", ["内置案例", "上传 PDF", "粘贴正文"], horizontal=True)
            pages: list[SourcePage] = []
            product: list[SourcePage] = []
            preset = UserScenario(question="")
            if mode == "内置案例":
                choices = load_cases()["cases"]
                case_key = st.selectbox("选择公告", ["B", "A", "C"], format_func=lambda k: choices[k]["label"])
                pages, product, preset = get_case(case_key)
                identity = f"sample:{case_key}"
            elif mode == "上传 PDF":
                uploaded = st.file_uploader("上传文字型 PDF（最大 10 MB / 20 页）", type=["pdf"])
                identity = "upload:" + (fingerprint(uploaded.getvalue().hex()) if uploaded else "empty")
                if uploaded:
                    try:
                        all_pages = read_pdf(uploaded.getvalue(), uploaded.name)
                        page_ids = st.multiselect("选择要分析的页码", [p.page for p in all_pages],
                                                  default=[p.page for p in all_pages], key="pages_" + identity)
                        pages = [p for p in all_pages if p.page in page_ids]
                        st.caption("若一页包含多份公告，请在下方调整该页正文，只保留目标公告。")
                    except ValueError as exc:
                        st.error(str(exc))
            else:
                pasted = st.text_area("粘贴公告正文", height=180, max_chars=12000,
                                      placeholder="请保留公告标题、日期、关键表格及其他提示事项。")
                identity = "paste"
                if pasted.strip():
                    pages = [SourcePage(source_id="manual_announcement", page=1, text=pasted.strip(),
                                        label="人工粘贴正文", is_original=False)]

            document_changed = st.session_state.get("document_identity") != identity
            if document_changed:
                reset_document()
                set_scenario(preset)
                st.session_state["document_identity"] = identity

            if pages:
                with st.expander("查看原文 / 调整分析范围", expanded=False):
                    edited_pages = []
                    for page in pages:
                        text = st.text_area(f"{page.label} · 页／段 {page.page}", page.text, height=180,
                                            key=f"source_{identity}_{page.source_id}_{page.page}")
                        if text != page.text:
                            edited_pages.append(SourcePage(source_id="manual_announcement", page=page.page,
                                                           text=text, label="人工调整的正文", is_original=False))
                        else:
                            edited_pages.append(page)
                    pages = [p for p in edited_pages if p.text.strip()]
                    if any(not p.is_original for p in pages):
                        st.info("调整或粘贴后的正文标记为人工提供文本，其摘录不冒充原始 PDF 引用。")
                    if product:
                        st.caption("随案例提供的产品基础资料（历史基线，不能覆盖公告更新）")
                        for p in product:
                            st.text(p.text)
            if mode != "内置案例":
                product_text = st.text_area("可选：该基金的产品基础资料", help="仅填写本次公告对应的产品资料；不会自动套用内置基金资料。")
                if product_text.strip():
                    product = [SourcePage(source_id="product", page=1, text=product_text, label="人工提供的产品资料", is_original=False)]

            source_hash = fingerprint([p.model_dump() for p in pages + product])
            previous_hash = st.session_state.get("active_source_hash")
            if previous_hash != source_hash:
                st.session_state["active_source_hash"] = source_hash
                # Never apply extracted facts to a different source selection.
                st.session_state.pop("facts", None)
                st.session_state["reviewed"] = False
                st.session_state["facts_confirmed"] = False

            if mode == "内置案例" and document_changed:
                restore_case_result(case_key, source_hash)
            if st.session_state.get("saved_result_path"):
                with st.expander("已载入历史分析 · 查看来源"):
                    st.caption("历史结果来源：" + st.session_state["saved_result_path"])
                    st.caption("结果来自已保存的模型分析，仍需核对事实与适用条件。")

            st.caption(f"已选 {len(pages)} 页／段 · 公告及资料共 {sum(len(p.text) for p in pages + product):,} 字符")
            extraction_key = fingerprint({"source": source_hash, "model": MODEL, "prompt": PROMPT_VERSION})
            ready = bool(pages)
            can_extract = ready and (bool(settings.api_key) or extraction_key in st.session_state["extraction_cache"])
            if st.button("提取公告事实", type="primary", disabled=not can_extract):
                try:
                    validate_sources(pages, product)
                    cache_key = fingerprint({"source": source_hash, "model": MODEL, "prompt": PROMPT_VERSION})
                    if cache_key in st.session_state["extraction_cache"]:
                        st.session_state["facts"] = deepcopy(st.session_state["extraction_cache"][cache_key])
                        st.session_state["notice"] = "复用当前会话中的提取结果，本次未调用模型。"
                    else:
                        with st.spinner("正在提取公告事实并核验引文…"):
                            facts = extract_facts(pages, product, settings, st.session_state["records"])
                        st.session_state["facts"] = facts
                        st.session_state["extraction_cache"][cache_key] = deepcopy(facts)
                        st.session_state["notice"] = "提取完成。请核对以下事实。"
                    st.session_state["facts_confirmed"] = False
                    st.session_state["reviewed"] = False
                    st.session_state["fact_revision"] += 1
                    st.rerun()
                except (PipelineError, ValueError) as exc:
                    st.error(str(exc))

        with st.container(key="facts-card"):
            facts = st.session_state.get("facts")
            if facts:
                render_facts(facts)
                facts = st.session_state["facts"]

            if not facts:
                st.caption("导入公告后，点击“提取公告事实”开始核对。")
    with scenario_tab:
        with st.container(key="scenario-card"):
            section_heading("02", "补充用户情境", "填写用户问题和业务条件，保存后生成针对性的回应。")
            render_scenario(facts)
            scenario = st.session_state["scenario"]
            valid_facts = facts is not None and facts.kind != Kind.OTHER and st.session_state.get("facts_confirmed", False)
            can_generate = bool(settings.api_key) or (facts is not None and
                           current_input_hash(facts, scenario) in st.session_state["material_cache"])
            if st.button("分析用户影响并生成材料", type="primary",
                         disabled=not (ready and valid_facts and st.session_state.get("scenario_saved") and can_generate)):
                try:
                    if not scenario.question.strip():
                        raise ValueError("请先填写用户问题。")
                    cache_key = current_input_hash(facts, scenario)
                    if cache_key in st.session_state["material_cache"]:
                        rules, draft = deepcopy(st.session_state["material_cache"][cache_key])
                        st.session_state["notice"] = "复用当前会话中相同输入的材料，本次未调用模型。"
                    else:
                        with st.spinner("正在计算业务影响并生成材料…"):
                            rules, draft = generate_materials(pages, product, facts, scenario, settings, st.session_state["records"])
                        st.session_state["material_cache"][cache_key] = deepcopy((rules, draft))
                    st.session_state.update(rules=rules, draft=draft, generated_facts=deepcopy(facts),
                                            generated_scenario=deepcopy(scenario), generated_rules=deepcopy(rules),
                                            material_input_hash=cache_key, reviewed=False,
                                            draft_revision=st.session_state.get("draft_revision", 0) + 1)
                    st.rerun()
                except (PipelineError, ValueError) as exc:
                    st.error(str(exc))
            if not valid_facts:
                st.caption("生成前请提取事实，并点击“确认并保存事实”。")
            elif not st.session_state.get("scenario_saved"):
                st.caption("请先保存用户情境，再生成材料。")
    with results_tab:
        with st.container(key="results-card"):
            if st.session_state.get("draft"):
                render_results(facts, scenario)
            else:
                section_heading("03", "审核与交付", "生成后可在此审核并编辑各渠道运营文案。")
                st.markdown('<div class="empty-state"><strong>让每一次回应，都准备充分。</strong>'
                            '<p>先在“公告与事实”中确认关键字段，再到“用户情境”保存问题并生成材料。<br>'
                            '客服回复、常见问答与 App 通知将在这里呈现。</p></div>', unsafe_allow_html=True)
    with overview.container():
        render_overview(stale=bool(st.session_state.get("draft")) and (
            facts is None or current_input_hash(facts, scenario) != st.session_state.get("material_input_hash")))
    st.markdown('<div class="footer-note">FundAssist · 公告解读与运营协作 / 内容经人工核对后使用</div>', unsafe_allow_html=True)



def render_facts(facts: AnnouncementFacts) -> None:
    section_heading("核对", "核对公告事实", "对照原文检查关键字段；修改后请确认保存，再进入“用户情境”。")
    if facts.kind == Kind.OTHER:
        st.warning("当前版本只支持基金经理变更、大额申购限制和基金分红三类公告。")
    st.caption(f"识别类型：{KIND_LABELS[facts.kind]} · 核对不代表系统已验证公告真实性")
    rows = [{"key": f.key, "字段": FIELD_LABELS[f.key], "值": f.value or "",
             "来源": {"announcement": "公告／所选文本", "product": "产品资料", "manual": "人工补充"}[f.origin]}
            for f in facts.facts]
    existing = {f.key for f in facts.facts}
    # Missing critical fields can be filled explicitly instead of silently inferred.
    required = {
        Kind.LIMIT: ["limit_start", "aggregate_limit", "aggregate_scope", "limit_account_scope", "limit_exclusive"],
        Kind.DIVIDEND: ["dividend_per", "dividend_base", "record_date", "default_method"],
        Kind.MANAGER: ["manager_leaving", "manager_remaining", "departure_reason", "departure_date"],
    }.get(facts.kind, [])
    rows += [{"key": k, "字段": FIELD_LABELS[k], "值": "", "来源": "尚未提供"} for k in required if k not in existing]
    with st.form(f"facts_form_{st.session_state['fact_revision']}"):
        edited = st.data_editor(rows, column_config={"key": None, "字段": st.column_config.TextColumn(width="medium"),
                               "值": st.column_config.TextColumn(width="large")},
                                disabled=["key", "字段", "来源"], hide_index=True, width="stretch",
                                key=f"fact_editor_{st.session_state['fact_revision']}")
        confirmed = st.form_submit_button("确认并保存事实")
    if confirmed:
        try:
            updated_rows = edited.to_dict("records") if hasattr(edited, "to_dict") else edited
            saved = save_facts(updated_rows, facts.kind, facts)
            evaluate_rules(saved, st.session_state["scenario"])
            st.session_state["facts"] = saved
            st.session_state["facts_confirmed"] = True
            st.session_state["reviewed"] = False
            st.success("事实已保存。改动字段会标记为人工补充；请继续保存情境并生成材料。")
        except ValueError as exc:
            st.error(str(exc))
    for conflict in facts.conflicts:
        st.warning("来源冲突：" + conflict)
    if facts.missing:
        st.caption("提取时发现的待核实项：" + "；".join(facts.missing))
    with st.expander("查看事实依据"):
        for f in facts.facts:
            if not f.value:
                continue
            st.markdown(f"**{FIELD_LABELS[f.key]}**：{f.value}")
            if f.origin == "manual":
                st.caption("人工补充，非原文引用。")
            for c in f.citations:
                st.caption(f"来源：{c.source_id} · 页／段 {c.page}")
                st.text(c.quote)


def render_scenario(facts: AnnouncementFacts | None) -> None:
    kind = facts.kind if facts else None
    with st.form("scenario_form"):
        st.text_area("用户问题", key="scenario_question", height=120, max_chars=3000)
        if kind == Kind.LIMIT:
            cols = st.columns(3)
            cols[0].text_input("同日申购金额（元）", key="scenario_purchase", help="未知请留空；已确认没有申请请填 0。")
            cols[1].text_input("同日定投金额（元）", key="scenario_recurring")
            cols[2].text_input("同日转换转入金额（元）", key="scenario_transfer")
            st.text_input("实际执行日期（未知可留空）", key="scenario_execution", placeholder="YYYY-MM-DD")
            st.caption("按同一账户、同一实际执行日填写。每月计划金额不能替代扣款日期及其他同日申请。")
        elif kind == Kind.DIVIDEND:
            cols = st.columns(2)
            cols[0].text_input("持有份额", key="scenario_shares")
            cols[1].selectbox("这些份额是否具备本次分红资格？", ["未知", "已确认", "不具备"], key="scenario_eligible")
            cols = st.columns(2)
            cols[0].selectbox("原分红方式", ["未知", "现金分红", "红利再投资"], key="scenario_original")
            cols[1].text_input("分红方式变更申请时间", key="scenario_change_time", placeholder="YYYY-MM-DD HH:MM")
            st.selectbox("本次适用的登记分红方式", ["未知", "现金分红", "红利再投资"], key="scenario_registry")
            st.checkbox("我已核实本次适用的注册登记记录（不是仅有提交回执）", key="scenario_registry_verified")
        save = st.form_submit_button("保存用户情境")
    if save:
        try:
            s = st.session_state
            method = {"未知": None, "现金分红": "cash", "红利再投资": "reinvest"}
            scenario = UserScenario(
                question=s["scenario_question"],
                purchase_amount=(s["scenario_purchase"].strip() or None) if kind == Kind.LIMIT else None,
                recurring_amount=(s["scenario_recurring"].strip() or None) if kind == Kind.LIMIT else None,
                transfer_amount=(s["scenario_transfer"].strip() or None) if kind == Kind.LIMIT else None,
                execution_date=parse_date(s["scenario_execution"].strip(), "执行日期") if kind == Kind.LIMIT else None,
                holding_shares=(s["scenario_shares"].strip() or None) if kind == Kind.DIVIDEND else None,
                eligible_shares={"未知": None, "已确认": True, "不具备": False}[s["scenario_eligible"]] if kind == Kind.DIVIDEND else None,
                original_method=method[s["scenario_original"]] if kind == Kind.DIVIDEND else None,
                change_requested_at=(s["scenario_change_time"].strip() or None) if kind == Kind.DIVIDEND else None,
                registry_method=method[s["scenario_registry"]] if kind == Kind.DIVIDEND else None,
                registry_verified=s["scenario_registry_verified"] if kind == Kind.DIVIDEND else False,
            )
            if not scenario.question.strip():
                raise ValueError("请填写用户问题。")
            if scenario.registry_verified and not scenario.registry_method:
                raise ValueError("已核实登记记录时，请选择本次适用的登记方式。")
            if facts:
                evaluate_rules(facts, scenario)
            s["scenario"] = scenario
            s["scenario_saved"] = True
            s["reviewed"] = False
            st.success("情境已保存。")
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.get("scenario_saved"):
        st.caption("生成使用最后一次点击“保存用户情境”的内容；表单编辑后请先保存。")


def render_results(current_facts: AnnouncementFacts | None, current_scenario: UserScenario) -> None:
    section_heading("03", "审核与交付", "核实业务判断，编辑各渠道文案，确认后下载交付。")
    s = st.session_state
    stale = current_facts is None or current_input_hash(current_facts, current_scenario) != s.get("material_input_hash")
    if stale:
        s["reviewed"] = False
        st.warning("输入已变更，下方为旧版本材料，已标记过期。请重新确认事实和情境后生成。")
    rules = s["generated_rules"]
    st.markdown('<div class="result-summary"><span>本次解读 · 关键结论</span><p>'
                + escape(s["draft"].summary) + '</p></div>', unsafe_allow_html=True)
    if rules.calculations:
        labels = {"known_daily_total": "已提供金额合计（元）", "aggregate_limit": "合并限额（元）",
                  "dividend_amount": "分红金额（元，见资格条件）", "dividend_formula": "分红计算式"}
        items = list(rules.calculations.items())
        for start in range(0, len(items), 3):
            row = items[start:start + 3]
            cols = st.columns(len(row))
            for col, (key, value) in zip(cols, row):
                if key == "dividend_formula":
                    col.caption(f"{labels[key]}：{value}")
                else:
                    col.metric(labels.get(key, key), value)
    with st.expander("查看计算与判断依据"):
        for text in rules.confirmed:
            st.write("✓ " + text)
        for text in rules.conditional:
            st.info(text)
    with st.expander(f"待核实事项（内部） · {len(rules.needs_check)} 项"):
        for text in rules.needs_check:
            st.write("• " + text)
        if not rules.needs_check:
            st.caption("暂无额外待核实事项，仍需人工核对对外材料。")
    draft = MaterialDraft.model_validate(s["draft"].model_dump())
    revision = s["draft_revision"]
    tabs = st.tabs(["客服回复", "常见问答", "App 通知", "内部核查"])
    with tabs[0]:
        summary = st.text_area("关键结论", draft.summary, key=f"summary_{revision}", on_change=invalidate_review)
        reply = st.text_area("客服回复正文", draft.customer_reply, height=240,
                             key=f"reply_{revision}", on_change=invalidate_review)
        st.caption("可直接在回复框中编辑，选中文字即可复制。")
    faqs = []
    with tabs[1]:
        for i, faq in enumerate(draft.faqs):
            q = st.text_input(f"问题 {i + 1}", faq.question, key=f"faq_q_{revision}_{i}", on_change=invalidate_review)
            a = st.text_area(f"回答 {i + 1}", faq.answer, key=f"faq_a_{revision}_{i}", on_change=invalidate_review)
            faqs.append({"question": q, "answer": a})
    with tabs[2]:
        title = st.text_input("App 标题", draft.app_title, key=f"title_{revision}", on_change=invalidate_review)
        body = st.text_area("App 正文（面向所有相关用户）", draft.app_body, height=200,
                            key=f"body_{revision}", on_change=invalidate_review)
        st.caption("可直接在标题和正文框中编辑，选中文字即可复制。")
    with tabs[3]:
        checks = st.text_area("内部核查清单（一行一项）", "\n".join(draft.internal_checks),
                              height=180, key=f"checks_{revision}", on_change=invalidate_review)
    edited = MaterialDraft(summary=summary, customer_reply=reply, faqs=faqs,
                           app_title=title, app_body=body,
                           internal_checks=[x for x in checks.splitlines() if x.strip()],
                           referenced_fact_keys=draft.referenced_fact_keys)
    s["draft"] = edited
    if not (reply.strip() and title.strip() and body.strip()):
        s["reviewed"] = False
        st.warning("正文为空，不能标记为已核对。")
    st.checkbox("已人工核对事实、金额、适用条件和对外措辞", key="reviewed",
                disabled=stale or not (reply.strip() and title.strip() and body.strip()))
    reviewed = bool(s["reviewed"]) and not stale
    st.caption("当前状态：" + ("已过期" if stale else "已人工核对" if reviewed else "待人工核对"))
    markdown = material_markdown(s["generated_facts"], s["generated_scenario"], rules, edited,
                                 reviewed=reviewed, stale=stale)
    cols = st.columns(2)
    cols[0].download_button("下载完整运营材料 Markdown", markdown, "基金公告运营材料.md",
                             "text/markdown", width="stretch")
    cols[1].download_button("下载本次输入与运行记录 JSON", records_json(s["records"],
                           facts=s["generated_facts"].model_dump(),
                           scenario=s["generated_scenario"].model_dump(mode="json"),
                           rules=rules.model_dump(), material=edited.model_dump(),
                           saved_result_path=s.get("saved_result_path"),
                           reviewed=reviewed, stale=stale), "基金公告运行记录.json", "application/json", width="stretch")


if __name__ == "__main__":
    main()
