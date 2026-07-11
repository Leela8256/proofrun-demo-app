"""judge_b.py — runs INSIDE the sandbox, next to uploaded gates.py + diff_guard.py.

Phase-B judgment: gates.certify_b over the evidence artifact, with the real
diff_guard as the tamper gate — the same call run_scenario.py makes. The
wrapper adds nothing and summarizes nothing.

Inputs:  /tmp/evidence_B.json  (written by proofrun-run.sh B)
         /work/patch.diff      (the unified diff that was applied)
Outputs: /tmp/verdict_B.json   (gates.certify_b output, verbatim)
         /tmp/final_B.json     ({schema, verdict, evidence, patch, patch_sha256}
                                — the single file the agent relays verbatim)

The patch text rides back verbatim because the orchestrator re-runs
diff_guard on its own copy of the rules: a verdict is only CERTIFIED if the
patch that the *orchestrator* sees is clean.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates            # uploaded, sha256-verified
from diff_guard import diff_guard  # uploaded, sha256-verified

EVIDENCE = Path("/tmp/evidence_B.json")
PATCH = Path("/work/patch.diff")


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text())
    patch_text = PATCH.read_text(encoding="utf-8", errors="replace")
    verdict = gates.certify_b(evidence, patch_text, diff_guard)

    Path("/tmp/verdict_B.json").write_text(json.dumps(verdict))
    Path("/tmp/final_B.json").write_text(json.dumps({
        "schema": "proofrun/final@1",
        "phase": "B",
        "verdict": verdict,
        "evidence": evidence,
        "patch": patch_text,
        "patch_sha256": hashlib.sha256(patch_text.encode()).hexdigest(),
    }))
    final_path = Path("/tmp/final_B.json")
    digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
    Path("/tmp/final_B.sha256").write_text(digest)
    nonce_file = Path("/work/nonce.txt")
    nonce = nonce_file.read_text().strip() if nonce_file.exists() else ""
    Path("/tmp/receipt.json").write_text(json.dumps({
        "schema": "proofrun/receipt@1",
        "phase": "B",
        "nonce": nonce,
    }))
    print("wrote /tmp/final_B.json + receipt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
