"""
gates.py (v2) — the proof layer of ProofRun.

Changes from v1:
  * Gates consume EVIDENCE (parsed artifacts), not runner callables. The same
    functions serve the M1 local harness and the M2 pipe nodes: whoever ran
    the sandbox hands over outcomes; the gate only judges.
  * New verdict EVIDENCE_INVALID + parse_evidence(): malformed or incomplete
    evidence is a first-class halt. A sloppy executor can cause a false halt,
    never a false certificate. The system fails closed.

Design rules (do not relax):
  1. The TEST records; the RUNNER script writes artifacts; the GATE judges.
     Nobody summarizes evidence — artifacts only.
  2. A failing test is not evidence. A test failing *for the reported reason*
     is evidence. NO_REPRO is a first-class outcome, not an error path.
  3. Pure functions: dict/dataclass in, dict out. No I/O, no globals, no
     framework imports — droppable into RocketRide IInstance.py unchanged.

Stdlib only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Any, Callable, Sequence

EVIDENCE_SCHEMA = "proofrun/evidence@1"
DEFAULT_ATTEMPTS = 3


# ─────────────────────────────────────────────────────────────────────
# Verdicts
# ─────────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    CERTIFIED        = "CERTIFIED"         # all gates green, diff clean
    NO_REPRO         = "NO_REPRO"          # failed, but not for the reported error
    BUG_ABSENT       = "BUG_ABSENT"        # test passed on HEAD
    FLAKY            = "FLAKY"             # attempts disagreed
    FIX_FAILED       = "FIX_FAILED"        # reproduced; patch didn't resolve it
    REGRESSION       = "REGRESSION"        # fixed the bug, broke the suite
    TAMPERED         = "TAMPERED"          # diff_guard rejected the patch
    EVIDENCE_INVALID = "EVIDENCE_INVALID"  # artifact malformed/incomplete

    @property
    def certified(self) -> bool:
        return self is Verdict.CERTIFIED


class GateStatus(str, Enum):
    REPRODUCED = "REPRODUCED"
    NO_REPRO   = "NO_REPRO"
    BUG_ABSENT = "BUG_ABSENT"
    FLAKY      = "FLAKY"
    PASSED     = "PASSED"
    FAILED     = "FAILED"
    INVALID    = "INVALID"


# ─────────────────────────────────────────────────────────────────────
# Evidence types + validation
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RunOutcome:
    """One execution of the repro spec inside the sandbox."""
    passed: bool
    observed: tuple[str, ...]     # page errors + console.error, in order
    failure_message: str          # test runner's failure text ("" if passed)
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {**asdict(self), "observed": list(self.observed)}


class EvidenceError(ValueError):
    """Raised by parsers when an artifact violates the contract."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise EvidenceError(msg)


def _parse_run(obj: Any, where: str) -> RunOutcome:
    _require(isinstance(obj, dict), f"{where}: run is not an object")
    _require(isinstance(obj.get("passed"), bool), f"{where}: 'passed' must be bool")
    obs = obj.get("observed")
    _require(isinstance(obs, list) and all(isinstance(x, str) for x in obs),
             f"{where}: 'observed' must be a list of strings")
    fm = obj.get("failure_message", "")
    _require(isinstance(fm, str), f"{where}: 'failure_message' must be a string")
    dur = obj.get("duration_ms", 0)
    _require(isinstance(dur, int) and dur >= 0, f"{where}: 'duration_ms' must be int>=0")
    return RunOutcome(passed=obj["passed"], observed=tuple(obs),
                      failure_message=fm, duration_ms=dur)


def parse_evidence_a(payload: Any, attempts: int = DEFAULT_ATTEMPTS) -> list[RunOutcome]:
    """Validate a phase-A artifact. Raises EvidenceError on any violation."""
    _require(isinstance(payload, dict), "evidence A: not a JSON object")
    _require(payload.get("schema") == EVIDENCE_SCHEMA,
             f"evidence A: schema != {EVIDENCE_SCHEMA!r}")
    _require(payload.get("phase") == "A", "evidence A: phase != 'A'")
    runs = payload.get("runs")
    _require(isinstance(runs, list), "evidence A: 'runs' missing or not a list")
    _require(len(runs) == attempts,
             f"evidence A: expected exactly {attempts} runs, got {len(runs)} "
             f"— an incomplete protocol proves nothing")
    return [_parse_run(r, f"evidence A run[{i}]") for i, r in enumerate(runs)]


def parse_evidence_b(payload: Any) -> tuple[RunOutcome, dict]:
    """Validate a phase-B artifact -> (repro_run, suite). Raises EvidenceError."""
    _require(isinstance(payload, dict), "evidence B: not a JSON object")
    _require(payload.get("schema") == EVIDENCE_SCHEMA,
             f"evidence B: schema != {EVIDENCE_SCHEMA!r}")
    _require(payload.get("phase") == "B", "evidence B: phase != 'B'")
    _require(payload.get("patch_applied") is True,
             "evidence B: 'patch_applied' is not true — nothing to verify")
    run = _parse_run(payload.get("repro_run"), "evidence B repro_run")
    suite = payload.get("suite")
    _require(isinstance(suite, dict) and isinstance(suite.get("passed"), bool),
             "evidence B: 'suite' missing or 'suite.passed' not bool")
    return run, suite


# ─────────────────────────────────────────────────────────────────────
# Error matching
#
# Reported text comes from a human pasting into Slack: truncated,
# re-wrapped, missing frames. Match on normalized *substring*, both
# directions. Never equality.
# ─────────────────────────────────────────────────────────────────────

_NOISE = re.compile(r"\s+")
MIN_MATCH_LEN = 12   # "error" would corroborate everything; refuse short needles


def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = _NOISE.sub(" ", s)
    for prefix in ("uncaught ", "error: ", "typeerror: ", "referenceerror: "):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def error_matches(reported: str, observed: Sequence[str]) -> str | None:
    """Return the observed line that corroborates `reported`, else None."""
    r = _normalize(reported)
    if len(r) < MIN_MATCH_LEN:
        return None
    for line in observed:
        o = _normalize(line)
        if r in o or o in r:
            return line
    return None


# ─────────────────────────────────────────────────────────────────────
# Gate A — did we reproduce the reported bug?  (judges phase-A outcomes)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    status: GateStatus
    halt: bool
    reason: str
    runs: list[dict] = field(default_factory=list)
    observed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status.value, "halt": self.halt,
                "reason": self.reason, "runs": self.runs, "observed": self.observed}


def gate_a(outcomes: Sequence[RunOutcome], error_text: str) -> GateResult:
    runs = [o.to_dict() for o in outcomes]

    def classify(o: RunOutcome) -> GateStatus:
        if o.passed:
            return GateStatus.BUG_ABSENT
        return (GateStatus.REPRODUCED if error_matches(error_text, o.observed)
                else GateStatus.NO_REPRO)

    verdicts = [classify(o) for o in outcomes]
    tally = Counter(verdicts)

    if len(tally) > 1:
        return GateResult(GateStatus.FLAKY, halt=True, runs=runs, reason=(
            f"{len(outcomes)} runs disagreed: "
            + ", ".join(f"{v.value}x{n}" for v, n in tally.items())
            + ". A nondeterministic test cannot be evidence."))

    status = verdicts[0]
    all_observed = [line for o in outcomes for line in o.observed]

    if status is GateStatus.BUG_ABSENT:
        return GateResult(status, halt=True, runs=runs, observed=all_observed, reason=(
            "The repro test passed on unmodified code. Either the report is wrong, "
            "the bug is already fixed, or the test does not exercise the reported "
            "path. No fix proposed."))

    if status is GateStatus.NO_REPRO:
        return GateResult(status, halt=True, runs=runs, observed=all_observed, reason=(
            "The repro test failed, but not for the reported reason.\n"
            f"  reported: {error_text!r}\n"
            f"  observed: {all_observed or '[] (no page or console errors)'}\n"
            f"  failure:  {outcomes[0].failure_message}\n"
            "This is a test defect, not a reproduction. No fix proposed, no fix claimed."))

    matched = error_matches(error_text, outcomes[0].observed)
    return GateResult(GateStatus.REPRODUCED, halt=False, runs=runs,
                      observed=all_observed, reason=(
        f"Failed {len(outcomes)}/{len(outcomes)} on unmodified code with the "
        f"reported error: {matched!r}"))


# ─────────────────────────────────────────────────────────────────────
# Gate B — did the patch fix it?  Silence is part of the fix: a patch
# that swallows the exception and renders nothing must not pass.
# ─────────────────────────────────────────────────────────────────────

def gate_b(outcome: RunOutcome) -> GateResult:
    if not outcome.passed:
        return GateResult(GateStatus.FAILED, halt=True, runs=[outcome.to_dict()],
                          observed=list(outcome.observed), reason=(
            f"Same repro test still fails after patch: {outcome.failure_message}"))
    if outcome.observed:
        return GateResult(GateStatus.FAILED, halt=True, runs=[outcome.to_dict()],
                          observed=list(outcome.observed), reason=(
            f"Test passes, but the page still emits errors: {list(outcome.observed)}. "
            "The patch suppressed the symptom without resolving the fault."))
    return GateResult(GateStatus.PASSED, halt=False, runs=[outcome.to_dict()],
                      reason="ProofRun test passes after patch. No page or console errors.")


# ─────────────────────────────────────────────────────────────────────
# Gate C — did anything else break?
# ─────────────────────────────────────────────────────────────────────

def gate_c(suite: dict) -> GateResult:
    passed = bool(suite.get("passed"))
    return GateResult(GateStatus.PASSED if passed else GateStatus.FAILED,
                      halt=not passed, runs=[suite], reason=(
        "Existing suite green." if passed
        else "Patch introduced a regression in the existing suite."))


# ─────────────────────────────────────────────────────────────────────
# Orchestration — verdicts from artifacts.
#
# certify_a(): the reproduce pipe / phase A.
# certify_b(): the verify pipe / phase B (requires a prior REPRODUCED).
# Both return report payloads on every path; there is no exception path
# out of a gate. EVIDENCE_INVALID is a verdict, not a crash.
# ─────────────────────────────────────────────────────────────────────

_GATE_A_VERDICT = {
    GateStatus.NO_REPRO:   Verdict.NO_REPRO,
    GateStatus.BUG_ABSENT: Verdict.BUG_ABSENT,
    GateStatus.FLAKY:      Verdict.FLAKY,
}


def _report(verdict: Verdict, gates: dict, reason: str) -> dict:
    return {"verdict": verdict.value, "certified": verdict.certified,
            "reason": reason, "gates": gates}


def certify_a(evidence_a: Any, error_text: str,
              attempts: int = DEFAULT_ATTEMPTS) -> dict:
    """Judge phase A. verdict in {REPRODUCED*, NO_REPRO, BUG_ABSENT, FLAKY,
    EVIDENCE_INVALID}. (*REPRODUCED is interim — reported so the orchestrator
    can offer the approval button; it is not a certification.)"""
    gates: dict[str, dict] = {}
    try:
        outcomes = parse_evidence_a(evidence_a, attempts)
    except EvidenceError as e:
        gates["gate_a"] = {"status": GateStatus.INVALID.value, "halt": True,
                           "reason": str(e)}
        return _report(Verdict.EVIDENCE_INVALID, gates,
                       f"Phase-A artifact rejected: {e}")

    a = gate_a(outcomes, error_text)
    gates["gate_a"] = a.to_dict()
    if a.halt:
        return _report(_GATE_A_VERDICT[a.status], gates, a.reason)
    return {"verdict": "REPRODUCED", "certified": False,
            "reason": a.reason, "gates": gates}


def certify_b(evidence_b: Any, patch_text: str,
              guard: Callable[[str], tuple[bool, str]]) -> dict:
    """Judge phase B + diff guard. verdict in {CERTIFIED, FIX_FAILED,
    REGRESSION, TAMPERED, EVIDENCE_INVALID}."""
    gates: dict[str, dict] = {}
    try:
        repro_run, suite = parse_evidence_b(evidence_b)
    except EvidenceError as e:
        gates["gate_b"] = {"status": GateStatus.INVALID.value, "halt": True,
                           "reason": str(e)}
        return _report(Verdict.EVIDENCE_INVALID, gates,
                       f"Phase-B artifact rejected: {e}")

    b = gate_b(repro_run)
    gates["gate_b"] = b.to_dict()
    if b.halt:
        return _report(Verdict.FIX_FAILED, gates, b.reason)

    c = gate_c(suite)
    gates["gate_c"] = c.to_dict()
    if c.halt:
        return _report(Verdict.REGRESSION, gates, c.reason)

    clean, why = guard(patch_text)
    gates["diff_guard"] = {"clean": clean, "reason": why}
    if not clean:
        return _report(Verdict.TAMPERED, gates, why)

    return _report(Verdict.CERTIFIED, gates, "All gates green. Diff clean.")
