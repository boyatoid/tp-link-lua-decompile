#!/usr/bin/env python3
"""Derive TP-Link's Lua 5.1 opcode permutation, with provenance for every entry.

TP-Link's LuCI .lua files are Lua 5.1 bytecode built with (a) the OpenWrt LNUM patch
and (b) *renumbered opcodes*, so stock unluac rejects them outright.

Stage 1 (evidence: vote)
  The firmware ships unmodified LuaSocket 2.0.2. Compile those same public sources with
  stock Lua 5.1.5, align proto-for-proto against the firmware copies, and vote
  fw_op -> std_op wherever the non-opcode operand bits are identical. Only pairs with
  byte-identical operands are counted, so a disagreement is visible rather than averaged
  away.

Stage 2 (evidence: shape)
  Opcodes LuaSocket never emits cannot be voted on. Classify them by operand shape over
  the whole firmware corpus and assign ascending-fw to ascending-std within each class:
    * appears only in vararg protos                  -> VARARG
    * C operand used (binary)                        -> MOD, POW
    * C always 0 (unary)                             -> UNM, NOT, LEN
  The unary run is anchored by CONCAT, which stage 1 already fixed immediately above it.
  Instruction frequency is reported as independent corroboration (%, # are common; ^ is
  rare), but is not what decides the assignment.

Usage:
  derive_opmap.py --fw-lua-dir <rootfs>/usr/lib/lua --ref-src <luasocket>/src \
                  --luac <path/to/lua-5.1.5/src/luac> [-o opmap.json]

Copyright (C) 2026 Andrew Boyer

This program is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this
program.  If not, see <https://www.gnu.org/licenses/>.
"""
import argparse, collections, json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from luabc import BC, NAMES

# LuaSocket modules that are byte-identical in the firmwares checked so far. http/smtp/tp
# differ by one proto (TP-Link patched them) and are rejected automatically by the
# proto-count guard, so listing them here is harmless.
REF_MODULES = ["ltn12", "mime", "socket", "ftp", "http", "smtp", "tp", "url"]
FW_CANDIDATES = {m: [f"{m}.lua", f"socket/{m}.lua"] for m in REF_MODULES}


def load_corpus(root):
    out = []
    for dp, _, fs in os.walk(root):
        for fn in fs:
            if fn.endswith(".lua"):
                p = os.path.join(dp, fn)
                try:
                    out.append((p, BC(open(p, "rb").read())))
                except Exception:
                    pass        # plain-text .lua files and non-5.1 blobs
    return out


def vote(fw_lua_dir, ref_src, luac, tmp):
    votes = collections.defaultdict(collections.Counter)
    report = []
    for mod in REF_MODULES:
        fw = next((os.path.join(fw_lua_dir, c) for c in FW_CANDIDATES[mod]
                   if os.path.exists(os.path.join(fw_lua_dir, c))), None)
        src = os.path.join(ref_src, f"{mod}.lua")
        if not fw or not os.path.exists(src):
            report.append((mod, "skipped", "source or firmware copy not found"))
            continue
        ref = os.path.join(tmp, f"{mod}.luac")
        if subprocess.run([luac, "-o", ref, src], capture_output=True).returncode:
            report.append((mod, "skipped", "luac failed"))
            continue
        a, b = BC(open(fw, "rb").read()), BC(open(ref, "rb").read())
        pa, pb = list(a.walk()), list(b.walk())
        if len(pa) != len(pb):
            report.append((mod, "skipped", f"{len(pa)} vs {len(pb)} protos (patched)"))
            continue
        n = 0
        for fa, fb in zip(pa, pb):
            if len(fa.code) != len(fb.code):
                continue
            n += 1
            for x, y in zip(fa.code, fb.code):
                if (x & ~0x3F) == (y & ~0x3F):
                    votes[x & 0x3F][y & 0x3F] += 1
        report.append((mod, "aligned", f"{n}/{len(pa)} protos"))
    return votes, report


def shape_stats(corpus, ops):
    st = {o: {"n": 0, "c_used": 0, "vararg": 0, "fixed": 0} for o in ops}
    for _, bc in corpus:
        for pr in bc.walk():
            isva = pr.four[2] != 0
            for ins in pr.code:
                op = ins & 0x3F
                if op not in st:
                    continue
                s = st[op]
                s["n"] += 1
                s["c_used"] += 1 if ((ins >> 14) & 0x1FF) else 0
                s["vararg"] += isva
                s["fixed"] += not isva
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw-lua-dir", required=True)
    ap.add_argument("--ref-src", required=True, help="LuaSocket 2.0.2 src/ directory")
    ap.add_argument("--luac", required=True, help="stock Lua 5.1.5 luac binary")
    ap.add_argument("-o", "--out", default="opmap.json")
    a = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        votes, report = vote(a.fw_lua_dir, a.ref_src, a.luac, tmp)
    print("reference alignment:")
    for mod, status, detail in report:
        print(f"  {mod:8s} {status:8s} {detail}")

    entries, dissent = {}, []
    for fw_op in sorted(votes):
        std, cnt = votes[fw_op].most_common(1)[0]
        tot = sum(votes[fw_op].values())
        entries[fw_op] = {"std": std, "name": NAMES[std], "evidence": "vote",
                          "votes": cnt, "total": tot}
        if cnt != tot:
            dissent.append((fw_op, dict(votes[fw_op])))

    corpus = load_corpus(a.fw_lua_dir)
    unmapped_fw = [o for o in range(38) if o not in entries]
    used = {e["std"] for e in entries.values()}
    unmapped_std = [o for o in range(38) if o not in used]
    print(f"\nvoted {len(entries)}/38 from {len(corpus)} corpus files; "
          f"{len(unmapped_fw)} unresolved: {unmapped_fw}")

    st = shape_stats(corpus, unmapped_fw)
    cls = {"vararg": [], "binary": [], "unary": []}
    for o in unmapped_fw:
        s = st[o]
        if s["n"] and s["fixed"] == 0:
            cls["vararg"].append(o)
        elif s["c_used"]:
            cls["binary"].append(o)
        else:
            cls["unary"].append(o)
    want = {"vararg": [o for o in unmapped_std if NAMES[o] == "VARARG"],
            "binary": [o for o in unmapped_std if NAMES[o] in ("MOD", "POW")],
            "unary":  [o for o in unmapped_std if NAMES[o] in ("UNM", "NOT", "LEN")]}

    print("\nshape classification of the unvoted opcodes:")
    for k in ("vararg", "binary", "unary"):
        fws, stds = sorted(cls[k]), want[k]
        if len(fws) != len(stds):
            sys.exit(f"ERROR: {k} class has {len(fws)} fw ops but {len(stds)} std slots; "
                     "the corpus may be too small to classify. Aborting rather than guess.")
        for fw_op, std in zip(fws, stds):          # ascending -> ascending
            s = st[fw_op]
            print(f"  fw {fw_op:2d} -> {NAMES[std]:7s} {k:7s} "
                  f"n={s['n']:5d} c_used={s['c_used']:4d} vararg={s['vararg']}/{s['n']}")
            entries[fw_op] = {"std": std, "name": NAMES[std], "evidence": f"shape:{k}",
                              "n": s["n"], "c_used": s["c_used"],
                              "vararg_only": s["fixed"] == 0}

    if sorted(e["std"] for e in entries.values()) != list(range(38)):
        sys.exit("ERROR: result is not a bijection over 0..37")
    if dissent:
        print("\nWARNING: dissenting votes (inspect before trusting):")
        for fw_op, d in dissent:
            print(f"  fw {fw_op}: {d}")

    doc = {
        "_comment": "TP-Link Lua 5.1 opcode permutation: fw opcode -> stock opcode.",
        "_method": "see derive_opmap.py docstring; 'vote' entries are byte-aligned "
                   "against public LuaSocket 2.0.2 sources, 'shape' entries are "
                   "classified by operand form because LuaSocket never emits them",
        "map": {str(k): entries[k]["std"] for k in sorted(entries)},
        "provenance": {str(k): entries[k] for k in sorted(entries)},
    }
    json.dump(doc, open(a.out, "w"), indent=2, sort_keys=False)
    by_ev = collections.Counter(e["evidence"].split(":")[0] for e in entries.values())
    print(f"\nwrote {a.out}: 38/38 bijection ({dict(by_ev)})")


if __name__ == "__main__":
    main()
