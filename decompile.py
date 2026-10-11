#!/usr/bin/env python3
"""Convert TP-Link Lua 5.1 bytecode to stock bytecode and decompile it with unluac.

  decompile.py --map opmap.json --in <rootfs>/usr/lib/lua --out lua_src \
               [--unluac unluac.jar] [--keep-bytecode work/remap]

Without --unluac, it only writes the converted bytecode, which any stock Lua 5.1
decompiler can then read.

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
import argparse, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from luabc import BC, emit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--unluac")
    ap.add_argument("--keep-bytecode")
    a = ap.parse_args()

    doc = json.load(open(a.map))
    m = {int(k): v for k, v in (doc.get("map", doc)).items()}
    if sorted(m.values()) != list(range(38)):
        sys.exit("map is not a bijection over 0..37")

    conv = skipped = done = failed = 0
    for dp, _, fs in os.walk(a.src):
        for fn in fs:
            if not fn.endswith(".lua"):
                continue
            src = os.path.join(dp, fn)
            rel = os.path.relpath(src, a.src)
            try:
                blob = emit(BC(open(src, "rb").read()), opmap=m)
            except Exception as e:
                # plain-text .lua files live alongside bytecode; copy them through
                head = open(src, "rb").read(4)
                if head[:1] != b"\x1b":
                    dst = os.path.join(a.out, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    open(dst, "wb").write(open(src, "rb").read())
                    skipped += 1
                else:
                    print(f"  convert failed: {rel}: {e}")
                    failed += 1
                continue
            conv += 1
            bc_path = os.path.join(a.keep_bytecode or a.out, rel + "c")
            os.makedirs(os.path.dirname(bc_path), exist_ok=True)
            open(bc_path, "wb").write(blob)
            if a.unluac:
                dst = os.path.join(a.out, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "w") as out:
                    r = subprocess.run(["java", "-jar", a.unluac, bc_path],
                                       stdout=out, stderr=subprocess.PIPE)
                if r.returncode:
                    os.unlink(dst)
                    failed += 1
                    print(f"  decompile failed: {rel}: "
                          f"{r.stderr.decode(errors='replace').strip().splitlines()[:1]}")
                else:
                    done += 1
                if not a.keep_bytecode:
                    os.unlink(bc_path)
    print(f"converted {conv}, decompiled {done}, copied-as-source {skipped}, failed {failed}")


if __name__ == "__main__":
    main()
