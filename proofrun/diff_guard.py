"""
diff_guard.py — the tamper gate of ProofRun (HANDOFF §3.4).

diff_guard(patch_text) -> (clean: bool, reason: str)

Reject (-> TAMPERED via gates.certify_b) when the diff:
  * contains any skip/force token:  test.skip · test.only · describe.skip ·
    it.skip · `|| true`
  * deletes any test file
  * changes anything under tests/ other than creating the proofrun spec itself

Design rules (same as gates.py — do not relax):
  1. Pure string checks. No LLM, no heuristics with judgment calls.
  2. Fail closed: an odd-looking diff is rejected with a reason, never
     waved through. A false halt is acceptable; a false certificate is not.
  3. Pure function: str in, (bool, str) out. No I/O, no globals — droppable
     into a RocketRide IInstance.py unchanged.

Stdlib only.
"""

from __future__ import annotations

# Tokens that neutralize a test instead of fixing the code. Checked against
# the whole patch text: a patch whose surroundings even touch these lines is
# suspicious enough to refuse (fail closed).
BANNED_TOKENS = (
    "test.skip",
    "test.only",
    "describe.skip",
    "it.skip",
    "|| true",
)

# The one file a patch may create under tests/: the repro spec itself.
PROOFRUN_SPEC_PATH = "tests/proofrun.spec.ts"

_TEST_PATH_MARKERS = ("tests/", ".spec.", ".test.")


def _is_test_path(path: str) -> bool:
    return any(marker in path for marker in _TEST_PATH_MARKERS)


def _strip_prefix(path: str) -> str:
    """'a/src/x.jsx' or 'b/src/x.jsx' -> 'src/x.jsx'; '/dev/null' unchanged."""
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _parse_file_ops(patch_text: str) -> list[dict]:
    """Walk unified-diff headers -> [{'old': path|None, 'new': path|None}].

    'old' is None for a file creation (--- /dev/null); 'new' is None for a
    deletion (+++ /dev/null). Paths have their a/ b/ prefixes stripped.
    """
    ops: list[dict] = []
    current: dict | None = None
    for line in patch_text.splitlines():
        if line.startswith("diff --git"):
            current = {"old": None, "new": None}
            ops.append(current)
        elif line.startswith("--- "):
            path = line[4:].split("\t")[0].strip()
            if current is None:
                current = {"old": None, "new": None}
                ops.append(current)
            current["old"] = None if path == "/dev/null" else _strip_prefix(path)
        elif line.startswith("+++ "):
            path = line[4:].split("\t")[0].strip()
            if current is None:
                current = {"old": None, "new": None}
                ops.append(current)
            current["new"] = None if path == "/dev/null" else _strip_prefix(path)
    return ops


def diff_guard(patch_text: str) -> tuple[bool, str]:
    """Return (clean, reason). clean=False means TAMPERED."""
    if not isinstance(patch_text, str) or not patch_text.strip():
        return False, "empty or non-string patch — nothing to certify"

    for token in BANNED_TOKENS:
        if token in patch_text:
            return False, f"patch contains banned token {token!r}"

    ops = _parse_file_ops(patch_text)
    if not ops:
        return False, "no file headers found — not a unified diff"

    for op in ops:
        old, new = op["old"], op["new"]

        # Deletion: old path exists, new is /dev/null.
        if old is not None and new is None and _is_test_path(old):
            return False, f"patch deletes test file {old!r}"

        # Any touch under tests/ other than creating the proofrun spec.
        for path in (old, new):
            if path is None or not path.startswith("tests/"):
                continue
            is_spec_creation = (
                path == PROOFRUN_SPEC_PATH and old is None and new == PROOFRUN_SPEC_PATH
            )
            if not is_spec_creation:
                return False, (
                    f"patch modifies {path!r} under tests/ — only creating "
                    f"{PROOFRUN_SPEC_PATH!r} is permitted"
                )

    return True, "diff clean: no skip tokens, no test-file changes"
