"""Case inputs and read-only access to previously saved real model results."""
from dataclasses import dataclass
import json
from pathlib import Path

from config import ROOT
from documents import fingerprint, validate_evidence
from models import (AnnouncementFacts, MaterialDraft, RuleResult, RunRecord,
                    SourcePage, UserScenario)
from ai_service import validate_materials
from rules import evaluate_rules


def load_cases() -> dict:
    return json.loads((ROOT / "data" / "cases.json").read_text(encoding="utf-8"))


def get_case(key: str) -> tuple[list[SourcePage], list[SourcePage], UserScenario]:
    data = load_cases()
    case = data["cases"][key]
    return ([SourcePage.model_validate(p) for p in case["pages"]],
            [SourcePage.model_validate(p) for p in data["product"]],
            UserScenario(question=case["question"], **case["scenario"]))


@dataclass
class SavedCaseResult:
    path: Path
    facts: AnnouncementFacts
    scenario: UserScenario
    rules: RuleResult
    material: MaterialDraft
    records: list[RunRecord]


def load_case_result(key: str, repeat: int = 1) -> SavedCaseResult | None:
    """Load the newest complete, matching result; never write or call the API."""
    pages, product, scenario = get_case(key)
    expected = fingerprint({"source": [p.model_dump() for p in pages],
                            "product": [p.model_dump() for p in product],
                            "scenario": scenario.model_dump(mode="json")})
    for path in sorted((ROOT / "output" / "real-runs").glob(f"*/{key}-{repeat}.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("is_real_model_run") is not True:
                continue
            saved_scenario = UserScenario.model_validate(data["scenario"])
            actual = fingerprint({"source": data["source"], "product": data["product"],
                                  "scenario": saved_scenario.model_dump(mode="json")})
            if actual != expected:
                continue
            records = [RunRecord.model_validate(r) for r in data["records"]]
            if not all(any(r.stage == stage and r.status == "completed" for r in records)
                       for stage in ("extract", "generate")):
                continue
            facts = AnnouncementFacts.model_validate(data["facts"])
            rules = RuleResult.model_validate(data["rules"])
            material = MaterialDraft.model_validate(data["material"])
            validate_evidence(facts, pages, product)
            if rules != evaluate_rules(facts, saved_scenario):
                continue
            validate_materials(material, facts, rules, saved_scenario)
            return SavedCaseResult(path, facts, saved_scenario, rules, material, records)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Failed or corrupt historical files remain untouched; try an older result.
            continue
    return None
