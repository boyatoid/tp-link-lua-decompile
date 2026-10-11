#!/usr/bin/env bash
# Re-derive the opcode map and diff it against the committed opmap.json.
set -euo pipefail
usage() { echo "usage: $0 <rootfs>/usr/lib/lua <luasocket-2.0.2>/src <lua-5.1.5>/src/luac" >&2; exit 2; }
[ $# -eq 3 ] || usage
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
python3 "$here/derive_opmap.py" --fw-lua-dir "$1" --ref-src "$2" --luac "$3" -o "$tmp/fresh.json"
python3 - "$here/opmap.json" "$tmp/fresh.json" <<'PY'
import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
am = {str(k): int(v) for k, v in a.get("map", a).items()}
bm = {str(k): int(v) for k, v in b.get("map", b).items()}
if am == bm:
    print(f"\nVERIFIED: re-derived map is identical to the committed one ({len(am)} opcodes)")
else:
    diff = [(k, am.get(k), bm.get(k)) for k in sorted(set(am) | set(bm), key=int)
            if am.get(k) != bm.get(k)]
    sys.exit(f"\nMISMATCH on {len(diff)} opcode(s) (fw, committed, fresh): {diff}")
PY
