"""Presentation helpers for the Streamlit workbench."""
from html import escape
from pathlib import Path

import streamlit as st

from config import MODEL
from models import KIND_LABELS


def apply_styles() -> None:
    css = Path(__file__).with_name("styles.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_header() -> None:
    st.markdown("""
<div class="workspace-header">
  <div class="eyebrow">OPERATIONS WORKSPACE <span>基金运营工作台</span></div>
  <div class="hero-line"><div>
    <h1>基金公告，<span>清晰解读。</span></h1>
    <p>从公告原文到客户回应，让每一次运营交付有据可依。</p>
  </div><div class="hero-seal" aria-hidden="true">原文可溯<br>判断有据</div></div>
</div>""", unsafe_allow_html=True)


def render_sidebar(api_configured: bool) -> None:
    with st.sidebar:
        st.markdown("""
<div class="brand"><span class="brand-mark">F<span>·</span></span>
  <div><strong>FundAssist</strong><small>基金公告运营助手</small></div></div>
<div class="sidebar-label">你的运营协作空间</div>
<div class="sidebar-intro">把复杂公告<br>变成清楚的回应。</div>
<div class="sidebar-description">核对关键事实，分析用户影响，<br>准备可审核、可交付的运营材料。</div>
<div class="sidebar-rule"></div>
<div class="sidebar-label">MODEL / 模型信息</div>""", unsafe_allow_html=True)
        st.markdown(f"""
<div class="model-card"><div class="model-provider"><span class="model-dot"></span>OpenAI</div>
  <strong>{escape(MODEL.rsplit('-2026', 1)[0])}</strong>
  <span class="model-version">{escape(MODEL)}</span>
</div>""", unsafe_allow_html=True)
        if api_configured:
            st.caption("● 模型服务已配置")
        else:
            st.warning("待配置模型服务")
            st.caption("可浏览已有案例。新内容生成需由管理员配置 OpenAI API 密钥。")
        st.markdown("""
<div class="sidebar-note"><span>使用说明</span><p>内置案例为虚构演示材料。生成内容请经人工核对后使用，会话内容请及时下载保存。</p></div>
""", unsafe_allow_html=True)


def section_heading(number: str, title: str, description: str) -> None:
    st.markdown(f"""
<div class="section-heading"><span class="section-number">{escape(number)}</span>
  <div><h2>{escape(title)}</h2><p>{escape(description)}</p></div></div>
""", unsafe_allow_html=True)


def render_overview(*, stale: bool = False) -> None:
    s = st.session_state
    facts = s.get("facts")
    kind = KIND_LABELS[facts.kind] if facts else "等待导入公告"
    name = facts.get("fund_name") if facts else None
    confirmed = bool(s.get("facts_confirmed"))
    draft = s.get("draft")
    status = ("需要重新生成" if stale else "已人工核对" if s.get("reviewed")
              else "待人工核对" if draft else "等待生成")
    status_class = "status-warning" if stale or (draft and not s.get("reviewed")) else ""
    st.markdown(f"""
<div class="overview">
  <div class="overview-item overview-source"><span class="overview-label">当前公告</span>
    <strong>{escape(kind)}</strong><small>{escape(name or '支持经理变更、申购限制与基金分红')}</small></div>
  <div class="overview-item"><span class="overview-label">事实核对</span>
    <strong>{'已确认' if confirmed else '待核对' if facts else '待提取'}</strong>
    <small>{len(facts.facts) if facts else 0} 项事实字段 · 原文依据可查</small></div>
  <div class="overview-item"><span class="overview-label">交付状态</span>
    <strong class="{status_class}">{status}</strong><small>客服回复 / FAQ / App 通知</small></div>
</div>""", unsafe_allow_html=True)
