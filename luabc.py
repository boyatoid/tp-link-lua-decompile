"""Lua 5.1 bytecode: header-aware parse, LNUM->stock constant conversion, opcode remap.

TP-Link's Lua is built with the OpenWrt LNUM patch (header integral byte = 4, extra
constant tag 9 = int32) AND with renumbered opcodes, so stock unluac rejects it.
"""
import struct

NAMES = ("MOVE LOADK LOADBOOL LOADNIL GETUPVAL GETGLOBAL GETTABLE SETGLOBAL SETUPVAL "
         "SETTABLE NEWTABLE SELF ADD SUB MUL DIV MOD POW UNM NOT LEN CONCAT JMP EQ LT LE "
         "TEST TESTSET CALL TAILCALL RETURN FORLOOP FORPREP TFORLOOP SETLIST CLOSE CLOSURE "
         "VARARG").split()
assert len(NAMES) == 38

class Proto:
    pass

class BC:
    def __init__(self, data):
        self.d = data
        if data[:4] != b'\x1bLua' or data[4] != 0x51:
            raise ValueError("not Lua 5.1 bytecode")
        self.sz_int, self.sz_size_t = data[7], data[8]
        self.sz_instr, self.sz_num, self.integral = data[9], data[10], data[11]
        self.p = 12
        self.main = self._func()
        if self.p != len(data):
            raise ValueError(f"{len(data) - self.p} trailing bytes")

    def _u(self, n):
        v = int.from_bytes(self.d[self.p:self.p + n], 'little')
        self.p += n
        return v

    def _int(self):
        return self._u(self.sz_int)

    def _str(self):
        n = self._u(self.sz_size_t)
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def _func(self):
        f = Proto()
        f.source = self._str()
        f.ld = self._int()
        f.lld = self._int()
        f.four = self.d[self.p:self.p + 4]      # nups, nparams, is_vararg, maxstacksize
        self.p += 4

        n = self._int()
        f.code = list(struct.unpack_from('<%dI' % n, self.d, self.p))
        self.p += 4 * n

        f.consts, f.strs = [], []
        for _ in range(self._int()):
            t = self.d[self.p]
            self.p += 1
            if t == 0:
                f.consts.append((0, None))
            elif t == 1:
                f.consts.append((1, self._u(1)))
            elif t == 3:
                f.consts.append((3, struct.unpack_from('<d', self.d, self.p)[0]))
                self.p += self.sz_num
            elif t == 4:
                s = self._str()
                f.strs.append(s[:-1] if s.endswith(b'\0') else s)
                f.consts.append((4, s))
            elif t == 9:                        # LNUM int32
                f.consts.append((9, struct.unpack_from('<i', self.d, self.p)[0]))
                self.p += 4
            else:
                raise ValueError(f"unknown constant tag {t} at {self.p - 1:#x}")

        f.protos = [self._func() for _ in range(self._int())]

        n = self._int()                         # lineinfo (count read separately:
        f.lineinfo = self.d[self.p:self.p + self.sz_int * n]   # += on an attribute
        self.p += self.sz_int * n                              # loads before RHS)

        f.locvars = []
        for _ in range(self._int()):
            nm = self._str(); s = self._int(); e = self._int()
            f.locvars.append((nm, s, e))
        f.upvals = [self._str() for _ in range(self._int())]
        return f

    def walk(self, f=None):
        f = self.main if f is None else f
        yield f
        for k in f.protos:
            yield from self.walk(k)

def emit(bc, opmap=None, keep_debug=True):
    """Re-emit as stock Lua 5.1 bytecode: integral=0, tag 9 -> double, opcodes remapped."""
    o = bytearray(bc.d[:12])
    o[11] = 0
    wi = lambda v: o.extend(v.to_bytes(bc.sz_int, 'little'))
    def ws(b):
        o.extend(len(b).to_bytes(bc.sz_size_t, 'little'))
        o.extend(b)
    def put(f):
        ws(f.source); wi(f.ld); wi(f.lld); o.extend(f.four)
        wi(len(f.code))
        for ins in f.code:
            if opmap is not None:
                ins = (ins & ~0x3f) | opmap[ins & 0x3f]
            o.extend(struct.pack('<I', ins))
        wi(len(f.consts))
        for t, v in f.consts:
            if t == 0:
                o.append(0)
            elif t == 1:
                o.append(1); o.append(v)
            elif t == 3:
                o.append(3); o.extend(struct.pack('<d', v))
            elif t == 4:
                o.append(4); ws(v)
            elif t == 9:
                o.append(3); o.extend(struct.pack('<d', float(v)))
        wi(len(f.protos))
        for k in f.protos:
            put(k)
        if keep_debug:
            wi(len(f.lineinfo) // bc.sz_int); o.extend(f.lineinfo)
            wi(len(f.locvars))
            for nm, s, e in f.locvars:
                ws(nm); wi(s); wi(e)
            wi(len(f.upvals))
            for nm in f.upvals:
                ws(nm)
        else:
            wi(0); wi(0); wi(0)
    put(bc.main)
    return bytes(o)
