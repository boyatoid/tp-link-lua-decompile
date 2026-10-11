# tplink-lua-opcodes

Recover the **renumbered Lua 5.1 opcode table** from TP-Link router firmware and
decompile the LuCI backend to readable source.

TP-Link's web backend ships as **compiled Lua 5.1 bytecode**, not source. It is non-standard in two independent ways, and both have to be undone before any
stock decompiler will touch it:

1. **OpenWrt LNUM patch.** The header's `lua_Number_integral` byte is `4` (stock writes
   `0` or `1`) and there is an extra constant tag `9` holding a 32-bit integer. unluac
   rejects the file at the header: *"invalid code for lua number integrality: 4"*.
2. **Renumbered opcodes.** The 38 opcodes are permuted relative to stock `lopcodes.h`.
   Fix only the header and every file fails in the validator instead, with
   *"Function doesn't end with implicit return"* — because `RETURN` is no longer 30.

This tool recovers the permutation **reproducibly, from public sources only**, and
decompiles the result.

## Prerequisites

You need an already-decrypted, extracted root filesystem — specifically its
`usr/lib/lua` directory. For TP-Link's signed/encrypted `fw-type:Cloud` router images,
[tp-link-decrypt](https://github.com/robbins/tp-link-decrypt) handles the decryption; see
its docs for extracting the UBI/squashfs that follows. Nothing here touches a device or a
network — it is pure offline analysis of files you already have.

Also needed: `python3` (3.8+, no third-party packages), a C toolchain to build stock
`luac`, and a JVM plus [unluac](https://sourceforge.net/projects/unluac/) if you want
source rather than just converted bytecode.

## Reproducing

```sh
# Lua 5.1.5     sha256 2640fc56a795f29d28ef15e13c34a47e223960b0240e8cb0a82d9b0738695333
#               https://www.lua.org/ftp/lua-5.1.5.tar.gz
# LuaSocket 2.0.2  sha256 4861d1d6589462ac638c8d096085e7b4fe12bb90263c84e13bac5c89b0b67475
#               https://github.com/lunarmodules/luasocket/archive/refs/tags/v2.0.2.tar.gz

./derive_opmap.py --fw-lua-dir <rootfs>/usr/lib/lua \
                  --ref-src    <luasocket-2.0.2>/src \
                  --luac       <lua-5.1.5>/src/luac \
                  -o opmap.json

./decompile.py --map opmap.json --in <rootfs>/usr/lib/lua --out lua_src \
               --unluac /path/to/unluac.jar
```

`./verify.sh <lua-dir> <luasocket-src> <luac>` re-derives the map and diffs it against
the committed `opmap.json`, so a reviewer never has to take the table below on trust.

## Method

**Stage 1 — alignment vote (32 of 38).** The firmware ships **unmodified LuaSocket
2.0.2**. Compiling those public sources with stock Lua 5.1.5 gives a byte-level twin of
the firmware's own bytecode: the instruction stream is identical except for the opcode
numbers. Walking both proto trees in parallel and voting `fw_op -> std_op` wherever the
*non-opcode operand bits are byte-identical* resolved 32 opcodes **with zero dissenting
votes**. The operand-equality condition is what makes this safe — a mismatched pairing
simply isn't counted, so disagreement would show up as dissent rather than being averaged
into a wrong answer. `http`, `smtp` and `tp` differ by exactly one proto (TP-Link patched
them) and are dropped automatically by the proto-count guard.

**Stage 2 — operand shape (the remaining 6).** `MOD POW UNM NOT LEN VARARG` are never
emitted by LuaSocket, so no vote is possible. They are classified by operand form across
the whole firmware corpus and assigned ascending-fw to ascending-std within each class:

| class | test | std slots |
|---|---|---|
| vararg | occurs **only** in protos with `is_vararg` set | `VARARG` |
| binary | the `C` operand is used | `MOD`, `POW` |
| unary | `C` is always 0 | `UNM`, `NOT`, `LEN` |

The unary run is anchored: stage 1 already fixed `fw 23 -> CONCAT (21)`, and `fw 20/21/22
-> 18/19/20` continues straight into it. The script refuses to guess — if a class has a
different number of firmware opcodes than std slots, it aborts instead of emitting a
partial map.

Measured frequencies corroborate the assignment independently, without being what decides
it: `LEN` n=1358 and `MOD` n=304 (`#` and `%` are everywhere in LuCI), against `POW` n=6
(`^` is rare) and `UNM` n=11. `VARARG` is unambiguous at 170/170 occurrences inside vararg
protos and 0 outside.

**Semantic cross-check.** Structure alone could in principle be self-consistent and still
wrong, so the output was checked for meaning. `admin/diag.lua` decompiles to:

```lua
"ping -c 2 -W %d -s %d %q 2>&1" % {timeout, pktsize, host}
```

a 3-element table against exactly 3 format specifiers — LuCI's `string.__mod` idiom. That
only type-checks if `MOD` is correct, and `#` appears only where a length makes sense.

## The map

Derived from **Archer AX21(US) V5.46, firmware 1.1.2 Build 20250814**. Other TP-Link
builds may permute differently — re-run the derivation rather than assuming.

| fw opcode | std opcode | name | evidence |
|---|---|---|---|
| 0 | 6 | `GETTABLE` | vote 356/356 |
| 1 | 5 | `GETGLOBAL` | vote 113/113 |
| 2 | 7 | `SETGLOBAL` | vote 41/41 |
| 3 | 8 | `SETUPVAL` | vote 21/21 |
| 4 | 9 | `SETTABLE` | vote 97/97 |
| 5 | 10 | `NEWTABLE` | vote 34/34 |
| 6 | 11 | `SELF` | vote 87/87 |
| 7 | 3 | `LOADNIL` | vote 26/26 |
| 8 | 1 | `LOADK` | vote 236/236 |
| 9 | 2 | `LOADBOOL` | vote 5/5 |
| 10 | 4 | `GETUPVAL` | vote 258/258 |
| 11 | 24 | `LT` | vote 2/2 |
| 12 | 25 | `LE` | vote 1/1 |
| 13 | 23 | `EQ` | vote 36/36 |
| 14 | 15 | `DIV` | vote 1/1 |
| 15 | 14 | `MUL` | vote 1/1 |
| 16 | 13 | `SUB` | vote 6/6 |
| 17 | 12 | `ADD` | vote 6/6 |
| 18 | 16 | `MOD` | shape:binary (n=304) |
| 19 | 17 | `POW` | shape:binary (n=6) |
| 20 | 18 | `UNM` | shape:unary (n=11) |
| 21 | 19 | `NOT` | shape:unary (n=44) |
| 22 | 20 | `LEN` | shape:unary (n=1358) |
| 23 | 21 | `CONCAT` | vote 22/22 |
| 24 | 22 | `JMP` | vote 219/219 |
| 25 | 26 | `TEST` | vote 101/101 |
| 26 | 27 | `TESTSET` | vote 22/22 |
| 27 | 0 | `MOVE` | vote 371/371 |
| 28 | 31 | `FORLOOP` | vote 3/3 |
| 29 | 32 | `FORPREP` | vote 3/3 |
| 30 | 33 | `TFORLOOP` | vote 3/3 |
| 31 | 34 | `SETLIST` | vote 6/6 |
| 32 | 35 | `CLOSE` | vote 1/1 |
| 33 | 36 | `CLOSURE` | vote 114/114 |
| 34 | 28 | `CALL` | vote 276/276 |
| 35 | 30 | `RETURN` | vote 276/276 |
| 36 | 29 | `TAILCALL` | vote 47/47 |
| 37 | 37 | `VARARG` | shape:vararg (n=170) |
## Caveats

- These firmware images are compiled **stripped**, so local variable names are gone and
  the output uses `L3_2`-style register names. Strings, control flow, call structure and
  constants are all intact, which is what matters for reading the code.
- `luci/debug.lua` ships as plain source rather than bytecode; `decompile.py` detects the
  missing `\x1b` signature and copies such files through unchanged.
- The map is per-build. Treat `opmap.json` as evidence for one firmware, not a universal
  constant. If you run this against another model, please open a PR with the resulting
  `opmap.json` and the firmware version — it is still an open question how widely TP-Link
  shares one permutation.
- Stage 1 depends on the firmware containing a library whose public source matches
  byte-for-byte. LuaSocket 2.0.2 worked here; on a build that patches it more heavily, the
  proto-count guard will reject the files and the vote will come up short. In that case,
  find another unmodified component rather than loosening the guard.

## Why not just patch unluac?

Patching a decompiler's opcode table requires knowing the permutation first, which is the
actual problem. This produces the table as *evidence* — with vote counts per entry — and
emits standard Lua 5.1 bytecode, so any stock tool can consume it.

## License

Not yet chosen; see the repo owner before redistributing. The derivation operates only on
public sources (lua.org, LuaSocket) and files already on your own device.
