#!/usr/bin/env bash
# proofrun-run.sh — runs INSIDE the sandbox (M1: local Docker; M2: Daytona).
#
# Produces the proofrun/evidence@1 artifact and nothing else. The TEST records,
# THIS script writes artifacts, the gate (outside) judges. No summarizing.
#
# Layout expected in the sandbox (uploaded/prepared by the executor):
#   $WORK/app                        cloned demo repo (phase B: virgin clone)
#   $WORK/proofrun.spec.template.ts  spec template with __ROUTE__/__EXPECTED__
#   $WORK/route.txt                  route, e.g. /cart?fixture=null-cart
#   $WORK/expected.txt               expected-behavior text
#   $WORK/patch.diff                 (phase B only) the unified diff to apply
#
# Usage:  proofrun-run.sh A [attempts]     -> /tmp/evidence_A.json  (default 3 runs)
#         proofrun-run.sh B                -> /tmp/evidence_B.json
#
# Injection safety (CLAUDE.md §5): everything that originated from the page
# under test or from test reports moves between steps as FILE CONTENTS only.
# Every embedded node script uses a quoted heredoc ('NODE') so the shell never
# expands anything inside it; placeholder filling is a fixed-string split/join,
# not sed/regex, so no delimiter or metacharacter can escape.

set -u
WORK="${PROOFRUN_WORK:-/work}"
APP="$WORK/app"
PHASE="${1:?usage: proofrun-run.sh A|B [attempts]}"
ATTEMPTS="${2:-3}"
export PROOFRUN_WORK="$WORK"

cd "$APP"

# ── deps: use the snapshot's seeded node_modules when present ────────────────
# An artifact must only exist if the protocol actually ran (CLAUDE.md §2).
# Deps or build failing means the protocol did NOT run: exit 70, write nothing.
# Three unanimous "passed=false, observed=[]" runs on a broken build would be
# an infrastructure failure laundered into a NO_REPRO verdict.
if [ ! -d node_modules ]; then
  if [ -d /seed/node_modules ]; then
    cp -r /seed/node_modules node_modules \
      || { echo "DEPS FAILED (seed copy) — no artifact" >&2; exit 70; }
  else
    npm ci --no-audit --no-fund >/tmp/npmci.log 2>&1 \
      || { echo "DEPS FAILED (npm ci) — no artifact" >&2; tail -50 /tmp/npmci.log >&2; exit 70; }
  fi
fi

# ── phase B: apply the patch on the virgin clone, record the outcome ─────────
PATCH_APPLIED=false
if [ "$PHASE" = "B" ]; then
  if git apply --whitespace=nowarn "$WORK/patch.diff"; then
    PATCH_APPLIED=true
  fi
fi
printf '%s' "$PATCH_APPLIED" > /tmp/patch_applied.txt

# ── fill the spec template from files (fixed-string replace, no regex) ───────
node - <<'NODE'
const fs = require('fs');
const work = process.env.PROOFRUN_WORK || '/work';
const tpl = fs.readFileSync(work + '/proofrun.spec.template.ts', 'utf8');
const route = fs.readFileSync(work + '/route.txt', 'utf8').trim();
const expected = fs.readFileSync(work + '/expected.txt', 'utf8').trim();
const out = tpl.split('__ROUTE__').join(route).split('__EXPECTED__').join(expected);
fs.writeFileSync(work + '/app/tests/proofrun.spec.ts', out);
NODE

# ── build once per phase (patch may have changed src/) ───────────────────────
npm run build >/tmp/build.log 2>&1 \
  || { echo "BUILD FAILED — no artifact" >&2; tail -50 /tmp/build.log >&2; exit 70; }

git rev-parse --short HEAD > /tmp/sha.txt

run_spec_once () {  # $1 = index; writes /tmp/run_$1.json
  rm -f /tmp/proofrun_observed.json /tmp/pw.json
  NO_COLOR=1 PLAYWRIGHT_JSON_OUTPUT_NAME=/tmp/pw.json \
    npx playwright test tests/proofrun.spec.ts --reporter=json >/dev/null 2>/tmp/pw.err || true
  RUN_INDEX="$1" node - <<'NODE'
const fs = require('fs');
const CAP_LINES = 20, CAP_CHARS = 500;
let passed = false, failure = '', duration = 0;
try {
  const r = JSON.parse(fs.readFileSync('/tmp/pw.json', 'utf8'));
  const specs = [];
  (function walk(s) {
    (s.suites || []).forEach(walk);
    (s.specs || []).forEach(x => specs.push(x));
  })({ suites: r.suites || [] });
  const results = specs.flatMap(sp => (sp.tests || []).flatMap(t => t.results || []));
  passed = specs.length > 0 && results.length > 0 && results.every(x => x.status === 'passed');
  duration = Math.round(results.reduce((a, x) => a + (x.duration || 0), 0));
  const err = results.map(x => x.error && x.error.message).find(Boolean);
  if (!passed) failure = String(err || (r.errors || []).map(e => e.message).join('; ') || 'test failed');
} catch (e) { failure = 'playwright report unreadable: ' + e.message; }
failure = failure.replace(/\x1b\[[0-9;]*m/g, '');  // reporter embeds ANSI even with NO_COLOR
let observed = [];
try { observed = JSON.parse(fs.readFileSync('/tmp/proofrun_observed.json', 'utf8')); } catch (e) {}
if (!Array.isArray(observed)) observed = [];
observed = observed.slice(0, CAP_LINES).map(s => String(s).slice(0, CAP_CHARS));
fs.writeFileSync('/tmp/run_' + process.env.RUN_INDEX + '.json', JSON.stringify({
  passed, observed,
  failure_message: failure.slice(0, CAP_CHARS * 2),
  duration_ms: duration
}));
NODE
}

if [ "$PHASE" = "A" ]; then
  rm -f /tmp/run_*.json
  for i in $(seq 1 "$ATTEMPTS"); do
    run_spec_once "$i"
  done
  ATTEMPTS="$ATTEMPTS" node - <<'NODE'
const fs = require('fs');
const work = process.env.PROOFRUN_WORK || '/work';
const n = parseInt(process.env.ATTEMPTS, 10);
const runs = [];
for (let i = 1; i <= n; i++)
  runs.push(JSON.parse(fs.readFileSync('/tmp/run_' + i + '.json', 'utf8')));
fs.writeFileSync('/tmp/evidence_A.json', JSON.stringify({
  schema: 'proofrun/evidence@1', phase: 'A',
  sha: fs.readFileSync('/tmp/sha.txt', 'utf8').trim(),
  route: fs.readFileSync(work + '/route.txt', 'utf8').trim(),
  runs
}));
NODE
  echo "wrote /tmp/evidence_A.json"
else
  run_spec_once repro
  # Gate C material: everything EXCEPT the proofrun spec ("did anything else break?")
  rm -f /tmp/pw.json
  NO_COLOR=1 PLAYWRIGHT_JSON_OUTPUT_NAME=/tmp/pw.json \
    npx playwright test --grep-invert proofrun --reporter=json >/dev/null 2>/tmp/pw.err || true
  node - <<'NODE'
const fs = require('fs');
let stats = {};
try { stats = JSON.parse(fs.readFileSync('/tmp/pw.json', 'utf8')).stats || {}; } catch (e) {}
const expected = stats.expected || 0, unexpected = stats.unexpected || 0;
fs.writeFileSync('/tmp/evidence_B.json', JSON.stringify({
  schema: 'proofrun/evidence@1', phase: 'B',
  sha: fs.readFileSync('/tmp/sha.txt', 'utf8').trim(),
  patch_applied: fs.readFileSync('/tmp/patch_applied.txt', 'utf8').trim() === 'true',
  repro_run: JSON.parse(fs.readFileSync('/tmp/run_repro.json', 'utf8')),
  suite: {
    passed: unexpected === 0 && expected > 0,
    total: expected + unexpected,
    failed: unexpected
  }
}));
NODE
  echo "wrote /tmp/evidence_B.json"
fi
