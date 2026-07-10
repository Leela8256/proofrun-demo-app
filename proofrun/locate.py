"""locate.py — runs INSIDE the sandbox. Locates the reported error in source.

Reads /work/needle.txt (the raw reported error — untrusted bytes that arrived
as file contents and are never interpolated into any command), extracts the
single-quoted identifiers a JS runtime embeds in its error messages
(e.g. "Cannot read properties of null (reading 'total')" -> total), and
scans the cloned repo's src/ for them. The raw message itself cannot appear
in source — it is a runtime artifact — which is why tokens, extracted
deterministically from the needle file, are what gets searched.

Consults /work/app/proofrun.map.json for the located file's registered route
and expected behavior.

Route resolution:
  * /work/route.txt present and non-empty (orchestrator supplied the route):
    the map row is recorded as corroboration data; a mismatch is DATA for the
    evidence trail, never a verdict.
  * /work/route.txt absent/empty: the map is the only route source. No grep
    hit or no map entry -> exit 71 with no artifact: a halt, not a guess.

Writes /tmp/location.json. Pure stdlib. No shell touches the needle.
"""
import json
import re
import sys
from pathlib import Path

WORK = Path("/work")
APP = WORK / "app"
OUT = Path("/tmp/location.json")

MIN_TOKEN_LEN = 3
SRC_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}


def fail_halt(reason: str) -> None:
    sys.stderr.write(f"LOCATE HALT: {reason}\n")
    sys.exit(71)


def main() -> int:
    needle = (WORK / "needle.txt").read_text(encoding="utf-8", errors="replace")
    tokens = sorted({t for t in re.findall(r"'([^']*)'", needle)
                     if len(t) >= MIN_TOKEN_LEN})

    route_file = WORK / "route.txt"
    have_route = route_file.exists() and route_file.read_text().strip() != ""

    hits: dict[str, list[int]] = {}
    if tokens:
        for path in sorted((APP / "src").rglob("*")):
            if not path.is_file() or path.suffix not in SRC_EXTS:
                continue
            rel = str(path.relative_to(APP))
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if any(t in line for t in tokens):
                    hits.setdefault(rel, []).append(lineno)

    located = None
    if hits:
        # most distinct hit lines wins; ties break lexicographically
        best = sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))[0]
        located = {"file": best[0], "line": best[1][0], "hit_lines": best[1]}

    map_path = APP / "proofrun.map.json"
    map_row = None
    if located and map_path.exists():
        table = json.loads(map_path.read_text())
        map_row = table.get(located["file"])

    if not have_route:
        # The map is the only route source here. Refuse to guess.
        if not located:
            fail_halt("no source file matched the reported error's identifiers; "
                      "cannot derive a route")
        if not map_row:
            fail_halt(f"located {located['file']} but it has no proofrun.map.json "
                      "entry; cannot derive a route")
        (WORK / "route.txt").write_text(map_row["route"])
        (WORK / "expected.txt").write_text(map_row["expected_behavior"])

    corroborates = None
    if have_route and map_row:
        corroborates = map_row["route"] == route_file.read_text().strip()

    OUT.write_text(json.dumps({
        "tokens": tokens,
        "located": located,
        "map_row": map_row,
        "route_source": "payload" if have_route else "map",
        "map_corroborates_route": corroborates,
    }))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
