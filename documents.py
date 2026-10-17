"""Text-only PDF intake and evidence checks; no OCR or remote file upload."""
from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata

from pypdf import PdfReader

from models import AnnouncementFacts, Citation, DATE_FIELDS, NUMERIC_FIELDS, SourcePage

MAX_CHARS = 12_000
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20


def fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def read_pdf(data: bytes, filename: str) -> list[SourcePage]:
    if len(data) > MAX_BYTES:
        raise ValueError("PDF 超过 10 MB，请缩小文件。")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF 已加密，请先解除密码或粘贴正文。")
        if len(reader.pages) > MAX_PAGES:
            raise ValueError("PDF 超过 20 页，请先拆分文件。")
        pages = [SourcePage(source_id="announcement", page=i + 1,
                            text=p.extract_text() or "", label=filename)
                 for i, p in enumerate(reader.pages)]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("PDF 无法读取，请上传有效的文字型 PDF，或粘贴正文。") from exc
    if not any(p.text.strip() for p in pages):
        raise ValueError("没有提取到文字；扫描件暂不支持，请粘贴公告正文。")
    return pages


def validate_sources(pages: list[SourcePage], product: list[SourcePage]) -> None:
    if not pages or not any(p.text.strip() for p in pages):
        raise ValueError("请先提供公告正文。")
    if len(pages) > MAX_PAGES:
        raise ValueError("一次最多分析 20 页。")
    if sum(len(p.text) for p in pages + product) > MAX_CHARS:
        raise ValueError("公告和产品资料合计超过 12,000 字符，请缩小分析范围；系统不会自动截断。")
    locations = [(p.source_id, p.page) for p in pages + product]
    if len(set(locations)) != len(locations):
        raise ValueError("来源页码重复，请重新选择输入。")


def validate_evidence(facts: AnnouncementFacts, pages: list[SourcePage],
                      product: list[SourcePage]) -> None:
    sources = {(p.source_id, p.page): p for p in pages + product}
    seen: set[str] = set()
    for fact in facts.facts:
        if fact.key in seen:
            raise ValueError(f"事实字段重复：{fact.key}")
        seen.add(fact.key)
        if fact.origin == "manual":
            if fact.citations:
                raise ValueError("人工补充字段不能冒充原文引用。")
            continue
        if fact.value is None:
            continue
        if not fact.citations:
            raise ValueError(f"字段 {fact.key} 缺少原文依据。")
        quotes = []
        for citation in fact.citations:
            source = sources.get((citation.source_id, citation.page))
            if not source or not citation.quote.strip() or normalize(citation.quote) not in normalize(source.text):
                raise ValueError(f"字段 {fact.key} 的引文无法在指定原文中找到。")
            if (fact.origin == "product") != (source.source_id == "product"):
                raise ValueError(f"字段 {fact.key} 的来源类型与引文不一致。")
            quotes.append(citation.quote)
        if fact.key in NUMERIC_FIELDS:
            value = normalize(fact.value).replace(",", "")
            joined = normalize(" ".join(quotes)).replace(",", "")
            # Match complete numeric tokens: 10 must not match 10000.
            numbers = re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", joined)
            from decimal import Decimal, InvalidOperation
            try:
                if not any(Decimal(value) == Decimal(n) for n in numbers):
                    raise ValueError(f"字段 {fact.key} 的数值未出现在引文中。")
            except InvalidOperation as exc:
                raise ValueError(f"字段 {fact.key} 必须是纯数字。") from exc
        if fact.key in DATE_FIELDS:
            from datetime import date
            dates = re.findall(r"(\d{4})\s*(?:年|[-/])\s*(\d{1,2})\s*(?:月|[-/])\s*(\d{1,2})", " ".join(quotes))
            try:
                extracted = {date(int(y), int(m), int(d)).isoformat() for y, m, d in dates}
                if date.fromisoformat(fact.value).isoformat() not in extracted:
                    raise ValueError(f"字段 {fact.key} 的日期与引文不一致。")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"字段 {fact.key} 的日期与引文不一致，或未使用 YYYY-MM-DD。") from exc


def locate_citations(facts: AnnouncementFacts, pages: list[SourcePage],
                     product: list[SourcePage]) -> list[str]:
    """Repair only an unambiguous page locator, never fabricate or rewrite a quotation."""
    notes = []
    sources = pages + product
    for fact in facts.facts:
        located = []
        for cite in fact.citations:
            if not cite.quote.strip():
                located.append(cite)
                continue
            exact = [p for p in sources if p.source_id == cite.source_id
                     and normalize(cite.quote) in normalize(p.text)]
            if any(p.page == cite.page for p in exact):
                located.append(cite)
                continue
            if len(exact) == 1:
                notes.append(f"{fact.key}：引文逐字匹配唯一来源页，页码由 {cite.page} 修正为 {exact[0].page}；引文未改写。")
                cite.page = exact[0].page
                located.append(cite)
                continue
            # Some models concatenate two complete original sentences while skipping
            # an intervening one. Split only when EACH whole sentence matches uniquely.
            pieces = [part.strip() for part in re.split(r"(?<=[。；])", cite.quote) if part.strip()]
            matches = [[p for p in sources if p.source_id == cite.source_id
                        and normalize(part) in normalize(p.text)] for part in pieces]
            if len(pieces) > 1 and all(len(m) == 1 for m in matches):
                located.extend(Citation(source_id=cite.source_id, page=m[0].page, quote=part)
                               for part, m in zip(pieces, matches))
                notes.append(f"{fact.key}：将拼接的完整原句拆为 {len(pieces)} 条独立引文，每条均逐字匹配唯一来源页。")
            else:
                located.append(cite)
        fact.citations = located
    return notes
