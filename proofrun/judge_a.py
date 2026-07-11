"""judge_a.py — runs INSIDE the sandbox, next to an uploaded gates.py.

The judge is a process, not the model: this wrapper feeds the phase-A
artifact and the reported error (read from files) to gates.certify_a and
writes the verdict. It adds nothing and summarizes nothing.

Inputs:  /tmp/evidence_A.json  (written by proofrun-run.sh)
         /work/needle.txt      (the reported error, raw bytes)
         /tmp/location.json    (optional, written by locate.py)
Outputs: /tmp/verdict_A.json   (gates.certify_a output, verbatim)
         /tmp/final_A.json     ({schema, verdict, evidence, location} bundle
                                — the single file the agent relays verbatim)
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gates  # the uploaded, sha256-verified judge

EVIDENCE = Path("/tmp/evidence_A.json")
NEEDLE = Path("/work/needle.txt")
LOCATION = Path("/tmp/location.json")


def main() -> int:
    evidence = json.loads(EVIDENCE.read_text())
    error_text = NEEDLE.read_text(encoding="utf-8", errors="replace")
    verdict = gates.certify_a(evidence, error_text)

    location = None
    if LOCATION.exists():
        location = json.loads(LOCATION.read_text())

    Path("/tmp/verdict_A.json").write_text(json.dumps(verdict))
    Path("/tmp/final_A.json").write_text(json.dumps({
        "schema": "proofrun/final@1",
        "phase": "A",
        "verdict": verdict,
        "evidence": evidence,
        "location": location,
    }))
    final_path = Path("/tmp/final_A.json")
    digest = hashlib.sha256(final_path.read_bytes()).hexdigest()
    Path("/tmp/final_A.sha256").write_text(digest)
    nonce_file = Path("/work/nonce.txt")
    nonce = nonce_file.read_text().strip() if nonce_file.exists() else ""
    Path("/tmp/receipt.json").write_text(json.dumps({
        "schema": "proofrun/receipt@1",
        "phase": "A",
        "nonce": nonce,
    }))
    print("wrote /tmp/final_A.json + receipt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
