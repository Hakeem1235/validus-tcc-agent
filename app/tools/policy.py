"""Policy tools: rules loading, deterministic version selection, clause retrieval (BM25 filtered by version)."""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from datetime import date

import yaml

from app import config
from app.normalise import parse_date
from app.trace import current, tool


@functools.lru_cache(maxsize=1)
def rules() -> dict:
    with open(config.RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@functools.lru_cache(maxsize=1)
def _clauses() -> list[dict]:
    if not config.CLAUSES_PATH.exists():
        return []
    return json.loads(config.CLAUSES_PATH.read_text(encoding="utf-8"))


@dataclass
class PolicySelection:
    sop_version: str
    sop_effective_from: str
    addenda: list[dict] = field(default_factory=list)  # [{doc, version, effective_from}]
    warnings: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)

    @property
    def addendum_docs(self) -> list[str]:
        return [a["doc"] for a in self.addenda]

    def has(self, doc: str) -> bool:
        return doc in self.addendum_docs

    def sop_ref(self, clause_id: str) -> str:
        return f"TCC-SOP v{self.sop_version} {clause_id}"

    def as_dict(self) -> dict:
        return {"sop": {"document": "TCC-SOP", "version": self.sop_version, "effective_from": self.sop_effective_from},
                "addenda": self.addenda, "reasoning": self.reasoning, "warnings": self.warnings}


@tool("policy.select")
def select(received: date, amc: str | None) -> PolicySelection:
    """Pick the SOP version in force on `received` and any addendum in force for the AMC."""
    docs = rules()["documents"]
    sops = sorted([d for d in docs if d["doc"] == "TCC-SOP"], key=lambda d: d["effective_from"], reverse=True)
    warnings, reasoning = [], []
    chosen = None
    for d in sops:
        if parse_date(d["effective_from"]) <= received:
            chosen = d
            break
    if chosen is None:  # before the earliest known version
        chosen = sops[-1]
        warnings.append(f"Request date {received} precedes earliest available SOP (v{chosen['version']}, "
                        f"{chosen['effective_from']}); applied v{chosen['version']}.")
    reasoning.append(f"received {received} >= TCC-SOP v{chosen['version']} effective {chosen['effective_from']}")
    if chosen.get("available") is False:
        fb = next(d for d in sops if d["version"] == chosen["fallback_version"])
        warnings.append(f"TCC-SOP v{chosen['version']} (effective {chosen['effective_from']}) governs this date but is "
                        f"not in the policy library; applied v{fb['version']} (per revision history the change was "
                        f"limited to Annex A / automation role).")
        chosen = fb
    sel = PolicySelection(sop_version=chosen["version"], sop_effective_from=chosen["effective_from"],
                          warnings=warnings, reasoning=reasoning)
    if amc:
        adds = sorted([d for d in docs if d.get("addendum") and d["amc_scope"] == amc],
                      key=lambda d: d["effective_from"], reverse=True)
        for d in adds:
            if parse_date(d["effective_from"]) <= received:
                if d.get("available") is False:
                    sel.warnings.append(f"{d['doc']} (effective {d['effective_from']}) applies to {amc} on this date "
                                        f"but is not in the policy library; SOP applied without addendum.")
                else:
                    sel.addenda.append({"doc": d["doc"], "version": d["version"], "effective_from": d["effective_from"]})
                    sel.reasoning.append(f"{amc} folio and received {received} >= {d['doc']} effective {d['effective_from']}")
                break
        else:
            sel.reasoning.append(f"no {amc} addendum in force on {received}")
    t = current()
    if t:
        t.document("TCC-SOP", sel.sop_version)
        for a in sel.addenda:
            t.document(a["doc"], a["version"])
    return sel


@tool("policy.clause")
def clause(doc: str, version: str, clause_id: str) -> str | None:
    for c in _clauses():
        if c["doc"] == doc and c["version"] == version and c["clause_id"] == clause_id:
            return c["text"]
    return None


def _tok(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower())


@tool("policy.search")
def search(query: str, docs: list[tuple[str, str]], k: int = 3) -> list[dict]:
    """BM25 over clauses restricted to the given (doc, version) pairs."""
    from rank_bm25 import BM25Okapi

    pool = [c for c in _clauses() if (c["doc"], c["version"]) in set(docs) and c["clause_id"] != "header"]
    if not pool:
        return []
    bm = BM25Okapi([_tok(c["text"]) for c in pool])
    scores = bm.get_scores(_tok(query))
    ranked = sorted(zip(scores, pool), key=lambda x: -x[0])[:k]
    return [{"doc": c["doc"], "version": c["version"], "clause_id": c["clause_id"], "score": round(float(s), 3),
             "text": c["text"][:600]} for s, c in ranked if s > 0]
