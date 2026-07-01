#!/usr/bin/env python3
# =====================================================================
#   ac's gba emu 0.2  —  single-file GBA emulator      (files = off)
#   Team Flames / Samsoft · python 3.14 · tkinter · targets 60 fps
#
#   · VisualBoyAdvance-style GUI (File / Options / Help menus,
#     status bar w/ fps, scale 1x-3x, pause, reset, frameskip)
#   · theme: blue text #33ccff on black, black buttons/menus
#   · ARM7TDMI interpreter (full ARM data-proc / ldr / str / ldm /
#     stm / mul / swp / psr / bx / swi + Thumb formats 1-19)
#   · PPU: bitmap modes 3 / 4 / 5 (VBA-style software rasterize)
#   · HLE BIOS: VBlankIntrWait, Halt, Div, CpuSet, CpuFastSet
#   · built-in "meowdemo" ROM boots when no cart is loaded
#   · clean-room — public docs (GBATEK) only, zero VBA/Nintendo code
#
#   keys:  arrows = dpad   z = A   x = B   enter = start
#          rshift = select   a = L   s = R
# =====================================================================
# pr

import sys, time, math, tkinter as tk
from array import array
from tkinter import filedialog, messagebox

M32 = 0xFFFFFFFF

BLUE  = "#33ccff"
BLACK = "#000000"
DKBLU = "#001018"

# =====================================================================
#  built-in demo ROM  ("meowdemo") — hand-assembled ARM, mode 3
#  blue gradient + dpad-movable cyan block, vsynced
# =====================================================================

AL, EQ, NE, LT, GT = 0xE, 0x0, 0x1, 0xB, 0xC

def build_demo_rom():
    words, labels, patch = [], {}, []

    def dp_imm(op, rd, rn, imm, rot=0, s=0, cond=AL):
        words.append(cond << 28 | 1 << 25 | op << 21 | s << 20 |
                     rn << 16 | rd << 12 | (rot >> 1) << 8 | imm)

    def dp_reg(op, rd, rn, rm, sh=0, st=0, s=0, cond=AL):
        words.append(cond << 28 | op << 21 | s << 20 | rn << 16 |
                     rd << 12 | sh << 7 | st << 5 | rm)

    def ldc(rd, val):                     # load 32-bit const (mov+orr)
        if val == 0:
            dp_imm(0xD, rd, 0, 0); return
        first = True
        for pos in (0, 8, 16, 24):
            b = (val >> pos) & 0xFF
            if not b:
                continue
            rot = (32 - pos) % 32
            if first:
                dp_imm(0xD, rd, 0, b, rot); first = False
            else:
                dp_imm(0xC, rd, rd, b, rot)

    def hword(l, rd, rn, off=0, p=1, u=1, w=0, cond=AL):
        words.append(cond << 28 | p << 24 | u << 23 | 1 << 22 |
                     w << 21 | l << 20 | rn << 16 | rd << 12 |
                     ((off >> 4) & 0xF) << 8 | 0xB0 | (off & 0xF))

    def label(n):  labels[n] = len(words)
    def bra(cond, n):
        patch.append((len(words), cond, n)); words.append(0)

    # ---- boot ----
    ldc(10, 0x04000000)                   # r10 = IO
    ldc(0,  0x0403)                       # DISPCNT: mode 3 | BG2
    hword(0, 0, 10)
    ldc(9,  0x06000000)                   # r9  = VRAM
    ldc(11, 0x04000130)                   # r11 = KEYINPUT
    ldc(12, 0x7FE0)                       # r12 = cyan (BGR555)

    # ---- blue gradient backdrop ----
    dp_reg(0xD, 8, 0, 9)                  # r8 = vram ptr
    dp_imm(0xD, 3, 0, 0)                  # y = 0
    label("Y")
    dp_reg(0xD, 4, 0, 3, sh=3, st=1)      # r4 = y >> 3
    dp_reg(0xD, 4, 0, 4, sh=10, st=0)     # r4 <<= 10 (blue)
    dp_imm(0xC, 4, 4, 4)                  # | faint red
    dp_imm(0xD, 2, 0, 0)                  # x = 0
    label("X")
    hword(0, 4, 8, 2, p=0)                # strh r4,[r8],#2
    dp_imm(4, 2, 2, 1)
    dp_imm(0xA, 0, 2, 240, s=1)
    bra(NE, "X")
    dp_imm(4, 3, 3, 1)
    dp_imm(0xA, 0, 3, 160, s=1)
    bra(NE, "Y")

    dp_imm(0xD, 6, 0, 112)                # square x
    dp_imm(0xD, 7, 0, 72)                 # square y

    # ---- main loop ----
    label("MAIN")
    label("W0")                           # wait until NOT in vblank
    hword(1, 0, 10, 4)
    dp_imm(8, 0, 0, 1, s=1)
    bra(NE, "W0")
    label("W1")                           # wait for vblank
    hword(1, 0, 10, 4)
    dp_imm(8, 0, 0, 1, s=1)
    bra(EQ, "W1")

    hword(1, 0, 11)                       # r0 = keys (active low)

    # erase square (redraw gradient rows under it)
    dp_imm(0xD, 3, 0, 0)
    label("ER")
    dp_reg(4, 4, 7, 3)                    # rowy = y + j
    dp_reg(0xD, 5, 0, 4, sh=9, st=0)      # r5 = rowy*512
    dp_reg(2, 5, 5, 4, sh=5, st=0)        # -rowy*32  -> *480
    dp_reg(4, 5, 5, 6, sh=1, st=0)        # + x*2
    dp_reg(4, 5, 5, 9)                    # + vram
    dp_reg(0xD, 4, 0, 4, sh=3, st=1)      # gradient color
    dp_reg(0xD, 4, 0, 4, sh=10, st=0)
    dp_imm(0xC, 4, 4, 4)
    dp_imm(0xD, 2, 0, 0)
    label("EC")
    hword(0, 4, 5, 2, p=0)
    dp_imm(4, 2, 2, 1)
    dp_imm(0xA, 0, 2, 16, s=1)
    bra(NE, "EC")
    dp_imm(4, 3, 3, 1)
    dp_imm(0xA, 0, 3, 16, s=1)
    bra(NE, "ER")

    # dpad movement (bit clear = pressed)
    dp_imm(8, 0, 0, 0x10, s=1); dp_imm(4, 6, 6, 2, cond=EQ)   # right
    dp_imm(8, 0, 0, 0x20, s=1); dp_imm(2, 6, 6, 2, cond=EQ)   # left
    dp_imm(8, 0, 0, 0x40, s=1); dp_imm(2, 7, 7, 2, cond=EQ)   # up
    dp_imm(8, 0, 0, 0x80, s=1); dp_imm(4, 7, 7, 2, cond=EQ)   # down
    # clamp
    dp_imm(0xA, 0, 6, 0,   s=1); dp_imm(0xD, 6, 0, 0,   cond=LT)
    dp_imm(0xA, 0, 6, 224, s=1); dp_imm(0xD, 6, 0, 224, cond=GT)
    dp_imm(0xA, 0, 7, 0,   s=1); dp_imm(0xD, 7, 0, 0,   cond=LT)
    dp_imm(0xA, 0, 7, 144, s=1); dp_imm(0xD, 7, 0, 144, cond=GT)

    # draw square
    dp_imm(0xD, 3, 0, 0)
    label("DR")
    dp_reg(4, 4, 7, 3)
    dp_reg(0xD, 5, 0, 4, sh=9, st=0)
    dp_reg(2, 5, 5, 4, sh=5, st=0)
    dp_reg(4, 5, 5, 6, sh=1, st=0)
    dp_reg(4, 5, 5, 9)
    dp_imm(0xD, 2, 0, 0)
    label("DC")
    hword(0, 12, 5, 2, p=0)
    dp_imm(4, 2, 2, 1)
    dp_imm(0xA, 0, 2, 16, s=1)
    bra(NE, "DC")
    dp_imm(4, 3, 3, 1)
    dp_imm(0xA, 0, 3, 16, s=1)
    bra(NE, "DR")

    bra(AL, "MAIN")

    for i, cond, name in patch:           # resolve branches
        off = labels[name] - (i + 2)
        words[i] = cond << 28 | 0b101 << 25 | (off & 0xFFFFFF)

    return b"".join(w.to_bytes(4, "little") for w in words)


# =====================================================================
#  ARM7TDMI interpreter
# =====================================================================

class ARM7TDMI:
    BANKMAP = {0x10: "usr", 0x1F: "usr", 0x12: "irq", 0x13: "svc"}

    def __init__(self, bus):
        self.bus = bus
        self.reset()

    def reset(self):
        self.r = [0] * 16
        self.pc = 0x08000000
        self.thumb = False
        self.N = self.Z = self.C = self.V = 0
        self.I = 0
        self.mode = 0x1F                                # system
        self.banks = {"usr": (0x03007F00, 0),
                      "irq": (0x03007FA0, 0),
                      "svc": (0x03007FE0, 0)}
        self.spsr = {}
        self.r[13] = 0x03007F00
        self.halt = False

    # ---- modes / banked r13-r14 / cpsr ----
    def _bankname(self, m=None):
        return self.BANKMAP.get(self.mode if m is None else m, "usr")

    def switch_mode(self, m):
        old = self._bankname()
        new = self._bankname(m)
        if old != new:
            self.banks[old] = (self.r[13], self.r[14])
            self.r[13], self.r[14] = self.banks.get(new, (0, 0))
        self.mode = m

    def get_cpsr(self):
        return (self.N << 31) | (self.Z << 30) | (self.C << 29) | \
               (self.V << 28) | (self.I << 7) | \
               (0x20 if self.thumb else 0) | self.mode

    def set_cpsr(self, v):
        self.N = (v >> 31) & 1
        self.Z = (v >> 30) & 1
        self.C = (v >> 29) & 1
        self.V = (v >> 28) & 1
        self.I = (v >> 7) & 1
        self.thumb = bool(v & 0x20)
        self.switch_mode(v & 0x1F)

    def restore_spsr(self):
        b = self._bankname()
        if b != "usr" and b in self.spsr:
            self.set_cpsr(self.spsr[b])

    def irq(self):
        # hardware IRQ exception entry -> vectors to mini-BIOS @ 0x18
        if self.I:
            return
        self.halt = False
        sp = self.get_cpsr()
        self.switch_mode(0x12)
        self.spsr["irq"] = sp
        self.r[14] = (self.pc + 4) & M32
        self.I = 1
        self.thumb = False
        self.pc = 0x18

    # ---- register access (r15 = pipeline) ----
    def reg(self, i):
        if i == 15:
            return (self.pc + (2 if self.thumb else 4)) & M32
        return self.r[i]

    def set_reg(self, i, v):
        if i == 15:
            self.pc = v & (0xFFFFFFFE if self.thumb else 0xFFFFFFFC)
        else:
            self.r[i] = v & M32

    # ---- condition codes ----
    def cond(self, c):
        N, Z, C, V = self.N, self.Z, self.C, self.V
        if c == 0:  return Z == 1
        if c == 1:  return Z == 0
        if c == 2:  return C == 1
        if c == 3:  return C == 0
        if c == 4:  return N == 1
        if c == 5:  return N == 0
        if c == 6:  return V == 1
        if c == 7:  return V == 0
        if c == 8:  return C == 1 and Z == 0
        if c == 9:  return C == 0 or Z == 1
        if c == 10: return N == V
        if c == 11: return N != V
        if c == 12: return Z == 0 and N == V
        if c == 13: return Z == 1 or N != V
        return c == 14

    # ---- flag arithmetic ----
    def _add(self, a, b, c, s):
        t = a + b + c
        res = t & M32
        if s:
            self.C = 1 if t > M32 else 0
            self.V = ((~(a ^ b) & (a ^ res)) >> 31) & 1
            self.N = res >> 31
            self.Z = 1 if res == 0 else 0
        return res

    def _sub(self, a, b, c, s):
        return self._add(a, (~b) & M32, c, s)

    # ---- barrel shifter (op2) ----
    def shifted(self, op):
        v = self.reg(op & 0xF)
        st = (op >> 5) & 3
        C = self.C
        if op & 0x10:                                  # register amount
            amt = self.reg((op >> 8) & 0xF) & 0xFF
            if amt == 0:
                return v, C
            imm = False
        else:
            amt = (op >> 7) & 0x1F
            imm = True
        if st == 0:                                    # LSL
            if amt == 0: return v, C
            if amt < 32: return (v << amt) & M32, (v >> (32 - amt)) & 1
            if amt == 32: return 0, v & 1
            return 0, 0
        if st == 1:                                    # LSR
            if imm and amt == 0: amt = 32
            if amt < 32: return v >> amt, (v >> (amt - 1)) & 1
            if amt == 32: return 0, v >> 31
            return 0, 0
        if st == 2:                                    # ASR
            if imm and amt == 0: amt = 32
            sv = v - 0x100000000 if v & 0x80000000 else v
            if amt >= 32:
                f = M32 if v >> 31 else 0
                return f, v >> 31
            return (sv >> amt) & M32, (sv >> (amt - 1)) & 1
        # ROR
        if imm and amt == 0:                           # RRX
            return ((C << 31) | (v >> 1)) & M32, v & 1
        amt &= 31
        if amt == 0:
            return v, v >> 31
        return ((v >> amt) | (v << (32 - amt))) & M32, (v >> (amt - 1)) & 1

    # =========================== ARM ================================
    def exec_arm(self, op):
        top = (op >> 25) & 7

        if top == 5:                                    # B / BL
            off = op & 0xFFFFFF
            if off & 0x800000: off -= 0x1000000
            if op & (1 << 24): self.r[14] = self.pc
            self.pc = (self.pc + 4 + (off << 2)) & M32
            return

        if top == 0:
            if (op & 0x0FFFFFF0) == 0x012FFF10:         # BX
                v = self.reg(op & 0xF)
                self.thumb = bool(v & 1)
                self.pc = v & (0xFFFFFFFE if v & 1 else 0xFFFFFFFC)
                return
            if (op & 0x90) == 0x90:
                if (op & 0x60) == 0:                    # mul / swap
                    if (op & 0x0FB00FF0) == 0x01000090:
                        self._swp(op)
                    elif (op & 0x0F8000F0) == 0x00800090:
                        self._mull(op)
                    else:
                        self._mul(op)
                    return
                self._halfword(op)
                return

        if top <= 1:                                    # data proc / psr
            opc = (op >> 21) & 0xF
            if not (op & (1 << 20)) and 8 <= opc <= 0xB:
                self._psr(op)
                return
            self._dataproc(op)
            return

        if top in (2, 3):
            self._single(op); return
        if top == 4:
            self._block(op); return
        if (op & 0x0F000000) == 0x0F000000:
            self.swi((op >> 16) & 0xFF); return

    def _dataproc(self, op):
        opc = (op >> 21) & 0xF
        s = (op >> 20) & 1
        rn = (op >> 16) & 0xF
        rd = (op >> 12) & 0xF
        if op & (1 << 25):
            imm = op & 0xFF
            rot = ((op >> 8) & 0xF) << 1
            if rot:
                b = ((imm >> rot) | (imm << (32 - rot))) & M32
                sc = b >> 31
            else:
                b, sc = imm, self.C
        else:
            b, sc = self.shifted(op)
        a = self.reg(rn)

        ar = False
        if   opc in (0, 8):  res = a & b
        elif opc in (1, 9):  res = a ^ b
        elif opc == 0xC:     res = a | b
        elif opc == 0xD:     res = b
        elif opc == 0xE:     res = a & (~b & M32)
        elif opc == 0xF:     res = (~b) & M32
        elif opc in (2, 0xA): res = self._sub(a, b, 1, s); ar = True
        elif opc == 3:        res = self._sub(b, a, 1, s); ar = True
        elif opc in (4, 0xB): res = self._add(a, b, 0, s); ar = True
        elif opc == 5:        res = self._add(a, b, self.C, s); ar = True
        elif opc == 6:        res = self._sub(a, b, self.C, s); ar = True
        else:                 res = self._sub(b, a, self.C, s); ar = True

        if s and not ar:
            self.N = res >> 31
            self.Z = 1 if res == 0 else 0
            self.C = sc
        if 8 <= opc <= 0xB:                             # TST/TEQ/CMP/CMN
            return
        if rd == 15:
            if s:                                       # e.g. subs pc,lr,#4
                self.restore_spsr()
            self.set_reg(15, res)
            return
        self.set_reg(rd, res)

    def _mul(self, op):
        acc = (op >> 21) & 1
        s = (op >> 20) & 1
        rd = (op >> 16) & 0xF
        rn = (op >> 12) & 0xF
        res = self.r[op & 0xF] * self.r[(op >> 8) & 0xF]
        if acc: res += self.r[rn]
        res &= M32
        self.r[rd] = res
        if s:
            self.N = res >> 31
            self.Z = 1 if res == 0 else 0

    def _mull(self, op):
        signed = (op >> 22) & 1
        acc = (op >> 21) & 1
        s = (op >> 20) & 1
        rh = (op >> 16) & 0xF
        rl = (op >> 12) & 0xF
        a = self.r[op & 0xF]
        b = self.r[(op >> 8) & 0xF]
        if signed:
            if a & 0x80000000: a -= 0x100000000
            if b & 0x80000000: b -= 0x100000000
        res = a * b
        if acc:
            res += (self.r[rh] << 32) | self.r[rl]
        res &= 0xFFFFFFFFFFFFFFFF
        self.r[rl] = res & M32
        self.r[rh] = (res >> 32) & M32
        if s:
            self.N = (res >> 63) & 1
            self.Z = 1 if res == 0 else 0

    def _swp(self, op):
        byte = (op >> 22) & 1
        rn, rd, rm = (op >> 16) & 0xF, (op >> 12) & 0xF, op & 0xF
        addr = self.r[rn]
        if byte:
            t = self.bus.read8(addr)
            self.bus.write8(addr, self.r[rm] & 0xFF)
        else:
            t = self.bus.read32(addr & ~3)
            ro = (addr & 3) << 3
            if ro: t = ((t >> ro) | (t << (32 - ro))) & M32
            self.bus.write32(addr & ~3, self.r[rm])
        self.r[rd] = t

    def _psr(self, op):
        spsr_sel = (op >> 22) & 1
        if (op & 0x0FBF0000) == 0x010F0000:             # MRS
            if spsr_sel:
                v = self.spsr.get(self._bankname(), self.get_cpsr())
            else:
                v = self.get_cpsr()
            self.set_reg((op >> 12) & 0xF, v)
            return
        if op & (1 << 25):                              # MSR imm
            imm = op & 0xFF
            rot = ((op >> 8) & 0xF) << 1
            v = ((imm >> rot) | (imm << (32 - rot))) & M32 if rot else imm
        else:
            v = self.reg(op & 0xF)
        if spsr_sel:
            b = self._bankname()
            nv = self.spsr.get(b, 0)
            if op & (1 << 19):
                nv = (nv & 0x0FFFFFFF) | (v & 0xF0000000)
            if op & (1 << 16):
                nv = (nv & ~0xFF & M32) | (v & 0xFF)
            self.spsr[b] = nv
            return
        if op & (1 << 19):                              # flags field
            self.N = (v >> 31) & 1
            self.Z = (v >> 30) & 1
            self.C = (v >> 29) & 1
            self.V = (v >> 28) & 1
        if op & (1 << 16):                              # control field
            self.I = (v >> 7) & 1
            self.switch_mode(v & 0x1F)

    def _halfword(self, op):
        p = (op >> 24) & 1
        u = (op >> 23) & 1
        i = (op >> 22) & 1
        w = (op >> 21) & 1
        l = (op >> 20) & 1
        rn = (op >> 16) & 0xF
        rd = (op >> 12) & 0xF
        sh = (op >> 5) & 3
        off = (((op >> 4) & 0xF0) | (op & 0xF)) if i else self.reg(op & 0xF)
        base = self.reg(rn)
        if not u: off = -off
        addr = (base + off) & M32 if p else base
        if l:
            if sh == 1:
                v = self.bus.read16(addr & ~1)
            elif sh == 2:
                v = self.bus.read8(addr)
                if v & 0x80: v -= 0x100
                v &= M32
            else:
                v = self.bus.read16(addr & ~1)
                if v & 0x8000: v -= 0x10000
                v &= M32
            self.set_reg(rd, v)
        else:
            self.bus.write16(addr & ~1, self.reg(rd) & 0xFFFF)
        if (not p or w) and rn != 15 and not (l and rn == rd):
            self.r[rn] = (base + off) & M32

    def _single(self, op):
        p = (op >> 24) & 1
        u = (op >> 23) & 1
        b = (op >> 22) & 1
        w = (op >> 21) & 1
        l = (op >> 20) & 1
        rn = (op >> 16) & 0xF
        rd = (op >> 12) & 0xF
        off = self.shifted(op)[0] if op & (1 << 25) else op & 0xFFF
        base = self.reg(rn)
        if not u: off = -off
        addr = (base + off) & M32 if p else base
        if l:
            if b:
                v = self.bus.read8(addr)
            else:
                v = self.bus.read32(addr & ~3)
                ro = (addr & 3) << 3
                if ro: v = ((v >> ro) | (v << (32 - ro))) & M32
            self.set_reg(rd, v)
        else:
            v = self.reg(rd)
            if b:
                self.bus.write8(addr, v & 0xFF)
            else:
                self.bus.write32(addr & ~3, v)
        if (not p or w) and rn != 15 and not (l and rn == rd):
            self.r[rn] = (base + off) & M32

    def _block(self, op):
        p = (op >> 24) & 1
        u = (op >> 23) & 1
        s = (op >> 22) & 1
        w = (op >> 21) & 1
        l = (op >> 20) & 1
        rn = (op >> 16) & 0xF
        rlist = op & 0xFFFF
        base = self.r[rn]
        cnt = bin(rlist).count("1") * 4
        if u:
            a = base + (4 if p else 0)
            nb = base + cnt
        else:
            a = base - cnt + (0 if p else 4)
            nb = base - cnt
        newpc = None
        for i in range(16):
            if (rlist >> i) & 1:
                if l:
                    v = self.bus.read32(a & ~3)
                    if i == 15:
                        newpc = v
                    else:
                        self.r[i] = v
                else:
                    self.bus.write32(a & ~3,
                                     (self.pc + 4) & M32 if i == 15 else self.r[i])
                a += 4
        if w and not (l and (rlist >> rn) & 1):
            self.r[rn] = nb & M32
        if newpc is not None:
            if s:                                       # ldm ..,{..,pc}^
                self.restore_spsr()
            self.pc = newpc & (0xFFFFFFFE if self.thumb else 0xFFFFFFFC)

    # ---- HLE BIOS ----
    def swi(self, n):
        n &= 0xFF
        bus = self.bus
        if n in (0x02, 0x04, 0x05):                     # Halt / IntrWait / VBlankIntrWait
            self.halt = True
        elif n == 0x01:                                 # RegisterRamReset (light)
            pass
        elif n == 0x06:                                 # Div
            a, b = self.r[0], self.r[1]
            if a & 0x80000000: a -= 0x100000000
            if b & 0x80000000: b -= 0x100000000
            if b == 0:
                q, rm = 0, a
            else:
                q = int(a / b)
                rm = a - q * b
            self.r[0] = q & M32
            self.r[1] = rm & M32
            self.r[3] = abs(q) & M32
        elif n == 0x07:                                 # DivArm (r1/r0)
            self.r[0], self.r[1] = self.r[1], self.r[0]
            self.swi(0x06)
        elif n == 0x08:                                 # Sqrt
            self.r[0] = int(self.r[0] ** 0.5) & 0xFFFF
        elif n == 0x09:                                 # ArcTan
            t = self.r[0] & 0xFFFF
            if t & 0x8000: t -= 0x10000
            self.r[0] = int(math.atan(t / 16384.0) / math.pi * 0x8000) & 0xFFFF
        elif n == 0x0A:                                 # ArcTan2
            x, y = self.r[0] & 0xFFFF, self.r[1] & 0xFFFF
            if x & 0x8000: x -= 0x10000
            if y & 0x8000: y -= 0x10000
            self.r[0] = int(math.atan2(y, x) / (2 * math.pi) * 0x10000) & 0xFFFF
        elif n == 0x0D:                                 # GetBiosChecksum
            self.r[0] = 0xBAAE187F
        elif n == 0x0E:                                 # BgAffineSet
            self._bg_affine_set()
        elif n == 0x0F:                                 # ObjAffineSet
            self._obj_affine_set()
        elif n == 0x10:                                 # BitUnPack
            self._bit_unpack()
        elif n in (0x11, 0x12):                         # LZ77UnComp Wram/Vram
            self._lz77()
        elif n == 0x13:                                 # HuffUnComp (stub: zero-fill)
            size = bus.read32(self.r[0]) >> 8
            for i in range(0, size & ~1, 2):
                bus.write16(self.r[1] + i, 0)
        elif n in (0x14, 0x15):                         # RLUnComp Wram/Vram
            self._rl_uncomp()
        elif n in (0x0B, 0x0C):                         # CpuSet / CpuFastSet
            src, dst, ctl = self.r[0], self.r[1], self.r[2]
            cnt = ctl & 0x1FFFFF
            fill = (ctl >> 24) & 1
            word = True if n == 0x0C else bool((ctl >> 26) & 1)
            step = 4 if word else 2
            rd = bus.read32 if word else bus.read16
            wr = bus.write32 if word else bus.write16
            if fill:
                v = rd(src & ~(step - 1))
                for i in range(cnt):
                    wr((dst + i * step) & ~(step - 1), v)
            else:
                for i in range(cnt):
                    wr((dst + i * step) & ~(step - 1),
                       rd((src + i * step) & ~(step - 1)))

    def _lz77(self):
        bus = self.bus
        src, dst = self.r[0], self.r[1]
        size = bus.read32(src) >> 8
        src += 4
        out = bytearray()
        guard = 0
        while len(out) < size and guard < 0x400000:
            guard += 1
            flags = bus.read8(src); src += 1
            for _ in range(8):
                if len(out) >= size:
                    break
                if flags & 0x80:
                    b1 = bus.read8(src)
                    b2 = bus.read8(src + 1)
                    src += 2
                    ln = (b1 >> 4) + 3
                    disp = (((b1 & 0xF) << 8) | b2) + 1
                    for _ in range(ln):
                        out.append(out[-disp] if disp <= len(out) else 0)
                else:
                    out.append(bus.read8(src)); src += 1
                flags = (flags << 1) & 0xFF
        del out[size:]
        if len(out) & 1: out.append(0)
        for i in range(0, len(out), 2):
            bus.write16(dst + i, out[i] | out[i + 1] << 8)

    def _rl_uncomp(self):
        bus = self.bus
        src, dst = self.r[0], self.r[1]
        size = bus.read32(src) >> 8
        src += 4
        out = bytearray()
        guard = 0
        while len(out) < size and guard < 0x400000:
            guard += 1
            b = bus.read8(src); src += 1
            if b & 0x80:
                out += bytes([bus.read8(src)]) * ((b & 0x7F) + 3)
                src += 1
            else:
                ln = (b & 0x7F) + 1
                for _ in range(ln):
                    out.append(bus.read8(src)); src += 1
        del out[size:]
        if len(out) & 1: out.append(0)
        for i in range(0, len(out), 2):
            bus.write16(dst + i, out[i] | out[i + 1] << 8)

    def _bit_unpack(self):
        bus = self.bus
        src, dst, info = self.r[0], self.r[1], self.r[2]
        length = bus.read16(info)
        sw = bus.read8(info + 2)
        dw = bus.read8(info + 3)
        ofs = bus.read32(info + 4)
        zf = (ofs >> 31) & 1
        ofs &= 0x7FFFFFFF
        if sw not in (1, 2, 4, 8) or dw not in (1, 2, 4, 8, 16, 32):
            return
        buf = 0
        bits = 0
        for i in range(length):
            b = bus.read8(src + i)
            for pos in range(0, 8, sw):
                v = (b >> pos) & ((1 << sw) - 1)
                if v or zf:
                    v = (v + ofs) & M32
                buf |= (v & ((1 << dw) - 1) if dw < 32 else v) << bits
                bits += dw
                while bits >= 32:
                    bus.write32(dst, buf & M32)
                    dst += 4
                    buf >>= 32
                    bits -= 32

    def _obj_affine_set(self):
        bus = self.bus
        src, dst = self.r[0], self.r[1]
        cnt = self.r[2] & 0xFFFF
        stride = self.r[3]
        for _ in range(cnt):
            sx = bus.read16(src)
            sy = bus.read16(src + 2)
            al = bus.read16(src + 4)
            if sx & 0x8000: sx -= 0x10000
            if sy & 0x8000: sy -= 0x10000
            src += 8
            a = (al & 0xFF00) / 0x10000 * 2 * math.pi
            c, s_ = math.cos(a), math.sin(a)
            bus.write16(dst,              int(sx * c) & 0xFFFF)
            bus.write16(dst + stride,     int(-sx * s_) & 0xFFFF)
            bus.write16(dst + 2 * stride, int(sy * s_) & 0xFFFF)
            bus.write16(dst + 3 * stride, int(sy * c) & 0xFFFF)
            dst += 4 * stride

    def _bg_affine_set(self):
        bus = self.bus
        src, dst = self.r[0], self.r[1]
        cnt = self.r[2] & 0xFFFF
        for _ in range(cnt):
            ox = bus.read32(src)
            oy = bus.read32(src + 4)
            if ox & 0x80000000: ox -= 0x100000000
            if oy & 0x80000000: oy -= 0x100000000
            scx = bus.read16(src + 8)
            scy = bus.read16(src + 10)
            sx = bus.read16(src + 12)
            sy = bus.read16(src + 14)
            al = bus.read16(src + 16)
            if scx & 0x8000: scx -= 0x10000
            if scy & 0x8000: scy -= 0x10000
            if sx & 0x8000: sx -= 0x10000
            if sy & 0x8000: sy -= 0x10000
            src += 20
            a = (al & 0xFF00) / 0x10000 * 2 * math.pi
            c, s_ = math.cos(a), math.sin(a)
            pa = int(sx * c); pb = int(-sx * s_)
            pc = int(sy * s_); pd = int(sy * c)
            bus.write16(dst,     pa & 0xFFFF)
            bus.write16(dst + 2, pb & 0xFFFF)
            bus.write16(dst + 4, pc & 0xFFFF)
            bus.write16(dst + 6, pd & 0xFFFF)
            bus.write32(dst + 8,  (ox - (pa * scx + pb * scy)) & M32)
            bus.write32(dst + 12, (oy - (pc * scx + pd * scy)) & M32)
            dst += 16

    # ========================== THUMB ===============================
    def exec_thumb(self, op):
        r = self.r
        if op < 0x1800:                                 # F1 shifted move
            st = (op >> 11) & 3
            amt = (op >> 6) & 0x1F
            v = r[(op >> 3) & 7]
            if st == 0:
                if amt:
                    self.C = (v >> (32 - amt)) & 1
                    v = (v << amt) & M32
            elif st == 1:
                if amt == 0: amt = 32
                self.C = (v >> (amt - 1)) & 1 if amt <= 32 else 0
                v = v >> amt if amt < 32 else 0
            else:
                if amt == 0: amt = 32
                sv = v - 0x100000000 if v & 0x80000000 else v
                if amt >= 32:
                    self.C = v >> 31
                    v = M32 if v >> 31 else 0
                else:
                    self.C = (sv >> (amt - 1)) & 1
                    v = (sv >> amt) & M32
            r[op & 7] = v
            self.N = v >> 31
            self.Z = 1 if v == 0 else 0
            return
        if op < 0x2000:                                 # F2 add/sub
            imm = (op >> 10) & 1
            sub = (op >> 9) & 1
            b = (op >> 6) & 7
            bv = b if imm else r[b]
            a = r[(op >> 3) & 7]
            r[op & 7] = self._sub(a, bv, 1, 1) if sub else self._add(a, bv, 0, 1)
            return
        if op < 0x4000:                                 # F3 imm8 ops
            opc = (op >> 11) & 3
            rd = (op >> 8) & 7
            imm = op & 0xFF
            if opc == 0:
                r[rd] = imm
                self.N = 0
                self.Z = 1 if imm == 0 else 0
            elif opc == 1:
                self._sub(r[rd], imm, 1, 1)
            elif opc == 2:
                r[rd] = self._add(r[rd], imm, 0, 1)
            else:
                r[rd] = self._sub(r[rd], imm, 1, 1)
            return
        if op < 0x4400:                                 # F4 ALU
            opc = (op >> 6) & 0xF
            rs = (op >> 3) & 7
            rd = op & 7
            a, b = r[rd], r[rs]
            res = None
            if   opc == 0:  res = a & b
            elif opc == 1:  res = a ^ b
            elif opc in (2, 3, 4, 7):                   # LSL/LSR/ASR/ROR by reg
                fake = (b & 0xFF) and 1
                amt = b & 0xFF
                st = {2: 0, 3: 1, 4: 2, 7: 3}[opc]
                if amt == 0:
                    res = a
                else:
                    v = a
                    if st == 0:
                        if amt < 32:
                            self.C = (v >> (32 - amt)) & 1
                            res = (v << amt) & M32
                        elif amt == 32:
                            self.C = v & 1; res = 0
                        else:
                            self.C = 0; res = 0
                    elif st == 1:
                        if amt < 32:
                            self.C = (v >> (amt - 1)) & 1
                            res = v >> amt
                        elif amt == 32:
                            self.C = v >> 31; res = 0
                        else:
                            self.C = 0; res = 0
                    elif st == 2:
                        sv = v - 0x100000000 if v & 0x80000000 else v
                        if amt >= 32:
                            self.C = v >> 31
                            res = M32 if v >> 31 else 0
                        else:
                            self.C = (sv >> (amt - 1)) & 1
                            res = (sv >> amt) & M32
                    else:
                        amt &= 31
                        if amt == 0:
                            self.C = v >> 31; res = v
                        else:
                            self.C = (v >> (amt - 1)) & 1
                            res = ((v >> amt) | (v << (32 - amt))) & M32
            elif opc == 5:  res = self._add(a, b, self.C, 1); r[rd] = res; return
            elif opc == 6:  res = self._sub(a, b, self.C, 1); r[rd] = res; return
            elif opc == 8:  res = a & b                     # TST
            elif opc == 9:  res = self._sub(0, b, 1, 1); r[rd] = res; return
            elif opc == 0xA: self._sub(a, b, 1, 1); return  # CMP
            elif opc == 0xB: self._add(a, b, 0, 1); return  # CMN
            elif opc == 0xC: res = a | b
            elif opc == 0xD: res = (a * b) & M32
            elif opc == 0xE: res = a & (~b & M32)
            else:            res = (~b) & M32
            self.N = res >> 31
            self.Z = 1 if res == 0 else 0
            if opc not in (8, 0xA, 0xB):
                r[rd] = res
            return
        if op < 0x4800:                                 # F5 hi-reg / BX
            opc = (op >> 8) & 3
            rd = (op & 7) | ((op >> 4) & 8)
            rs = (op >> 3) & 0xF
            if opc == 0:
                self.set_reg(rd, (self.reg(rd) + self.reg(rs)) & M32)
            elif opc == 1:
                self._sub(self.reg(rd), self.reg(rs), 1, 1)
            elif opc == 2:
                self.set_reg(rd, self.reg(rs))
            else:                                       # BX
                v = self.reg(rs)
                self.thumb = bool(v & 1)
                self.pc = v & (0xFFFFFFFE if v & 1 else 0xFFFFFFFC)
            return
        if op < 0x5000:                                 # F6 pc-rel load
            rd = (op >> 8) & 7
            base = (self.pc + 2) & 0xFFFFFFFC
            r[rd] = self.bus.read32(base + (op & 0xFF) * 4)
            return
        if op < 0x6000:                                 # F7 / F8 reg offset
            ro = (op >> 6) & 7
            rb = (op >> 3) & 7
            rd = op & 7
            addr = (r[rb] + r[ro]) & M32
            if not op & 0x200:                          # F7
                l = (op >> 11) & 1
                b = (op >> 10) & 1
                if l:
                    if b:
                        r[rd] = self.bus.read8(addr)
                    else:
                        v = self.bus.read32(addr & ~3)
                        ro2 = (addr & 3) << 3
                        if ro2: v = ((v >> ro2) | (v << (32 - ro2))) & M32
                        r[rd] = v
                else:
                    if b:
                        self.bus.write8(addr, r[rd] & 0xFF)
                    else:
                        self.bus.write32(addr & ~3, r[rd])
            else:                                       # F8 sign/half
                sh = (op >> 10) & 3
                if sh == 0:
                    self.bus.write16(addr & ~1, r[rd] & 0xFFFF)
                elif sh == 1:
                    v = self.bus.read8(addr)
                    if v & 0x80: v -= 0x100
                    r[rd] = v & M32
                elif sh == 2:
                    r[rd] = self.bus.read16(addr & ~1)
                else:
                    v = self.bus.read16(addr & ~1)
                    if v & 0x8000: v -= 0x10000
                    r[rd] = v & M32
            return
        if op < 0x8000:                                 # F9 imm5 word/byte
            b = (op >> 12) & 1
            l = (op >> 11) & 1
            off = (op >> 6) & 0x1F
            rb = (op >> 3) & 7
            rd = op & 7
            if b:
                addr = (r[rb] + off) & M32
                if l:
                    r[rd] = self.bus.read8(addr)
                else:
                    self.bus.write8(addr, r[rd] & 0xFF)
            else:
                addr = (r[rb] + off * 4) & M32
                if l:
                    v = self.bus.read32(addr & ~3)
                    ro2 = (addr & 3) << 3
                    if ro2: v = ((v >> ro2) | (v << (32 - ro2))) & M32
                    r[rd] = v
                else:
                    self.bus.write32(addr & ~3, r[rd])
            return
        if op < 0x9000:                                 # F10 half imm
            l = (op >> 11) & 1
            addr = (r[(op >> 3) & 7] + ((op >> 6) & 0x1F) * 2) & M32
            rd = op & 7
            if l:
                r[rd] = self.bus.read16(addr & ~1)
            else:
                self.bus.write16(addr & ~1, r[rd] & 0xFFFF)
            return
        if op < 0xA000:                                 # F11 sp-rel
            l = (op >> 11) & 1
            rd = (op >> 8) & 7
            addr = (r[13] + (op & 0xFF) * 4) & M32
            if l:
                r[rd] = self.bus.read32(addr & ~3)
            else:
                self.bus.write32(addr & ~3, r[rd])
            return
        if op < 0xB000:                                 # F12 load address
            rd = (op >> 8) & 7
            if op & 0x800:
                r[rd] = (r[13] + (op & 0xFF) * 4) & M32
            else:
                r[rd] = (((self.pc + 2) & 0xFFFFFFFC) + (op & 0xFF) * 4) & M32
            return
        if (op & 0xFF00) == 0xB000:                     # F13 sp adjust
            v = (op & 0x7F) * 4
            r[13] = (r[13] - v if op & 0x80 else r[13] + v) & M32
            return
        if (op & 0xF600) == 0xB400:                     # F14 push/pop
            l = (op >> 11) & 1
            R = (op >> 8) & 1
            rlist = op & 0xFF
            if l:                                       # POP
                a = r[13]
                for i in range(8):
                    if (rlist >> i) & 1:
                        r[i] = self.bus.read32(a & ~3); a += 4
                if R:
                    v = self.bus.read32(a & ~3); a += 4
                    self.pc = v & 0xFFFFFFFE
                r[13] = a & M32
            else:                                       # PUSH
                cnt = bin(rlist).count("1") + R
                a = (r[13] - cnt * 4) & M32
                r[13] = a
                for i in range(8):
                    if (rlist >> i) & 1:
                        self.bus.write32(a & ~3, r[i]); a += 4
                if R:
                    self.bus.write32(a & ~3, r[14])
            return
        if op < 0xD000:                                 # F15 ldmia/stmia
            l = (op >> 11) & 1
            rb = (op >> 8) & 7
            rlist = op & 0xFF
            a = r[rb]
            for i in range(8):
                if (rlist >> i) & 1:
                    if l:
                        r[i] = self.bus.read32(a & ~3)
                    else:
                        self.bus.write32(a & ~3, r[i])
                    a += 4
            if not (l and (rlist >> rb) & 1):
                r[rb] = a & M32
            return
        if op < 0xE000:                                 # F16 cond branch / swi
            c = (op >> 8) & 0xF
            if c == 0xF:
                self.swi(op & 0xFF)
                return
            if self.cond(c):
                off = op & 0xFF
                if off & 0x80: off -= 0x100
                self.pc = (self.pc + 2 + (off << 1)) & M32
            return
        if op < 0xF000:                                 # F18 branch
            off = op & 0x7FF
            if off & 0x400: off -= 0x800
            self.pc = (self.pc + 2 + (off << 1)) & M32
            return
        # F19 BL (two halves)
        off = op & 0x7FF
        if not op & 0x800:
            if off & 0x400: off -= 0x800
            self.r[14] = (self.pc + 2 + (off << 12)) & M32
        else:
            nxt = self.pc
            self.pc = (self.r[14] + (off << 1)) & 0xFFFFFFFE
            self.r[14] = (nxt | 1) & M32

    # ---- run n instructions ----
    def run(self, n):
        if self.halt:
            return
        bus = self.bus
        romw, romh, nrom = bus.romw, bus.romh, len(bus.rom)
        while n > 0:
            n -= 1
            pc = self.pc
            if not self.thumb:
                if pc >= 0x08000000 and (pc & 0x1FFFFFF) + 4 <= nrom:
                    op = romw[(pc & 0x1FFFFFF) >> 2]
                else:
                    op = bus.read32(pc & ~3)
                self.pc = (pc + 4) & M32
                c = op >> 28
                if c == 14 or self.cond(c):
                    self.exec_arm(op)
            else:
                if pc >= 0x08000000 and (pc & 0x1FFFFFF) + 2 <= nrom:
                    op = romh[(pc & 0x1FFFFFF) >> 1]
                else:
                    op = bus.read16(pc & ~1)
                self.pc = (pc + 2) & M32
                self.exec_thumb(op)
            if self.halt:
                return


# =====================================================================
#  GBA system: bus + PPU + keypad
# =====================================================================

class GBA:
    def __init__(self):
        self.ew = bytearray(0x40000)
        self.iw = bytearray(0x8000)
        self.io = bytearray(0x400)
        self.pal = bytearray(0x400)
        self.vram = bytearray(0x18000)
        self.oam = bytearray(0x400)
        self.sram = bytearray(0x10000)
        self.rom = b""
        self.romw = array("I")
        self.romh = array("H")
        self.keys = 0x3FF
        self.vcount = 0
        self.vblank = 0
        self.hblank = 0
        self.iflags = 0
        self.dsrc = [0] * 4
        self.ddst = [0] * 4
        self.tre = [0] * 4                              # timer reloads
        self.tc = [0] * 4                               # timer counters
        self.tacc = [0] * 4
        self.budget = 12000
        self.blue_hue = True
        self.lut = self.build_lut(True)
        self.bios = self._build_bios()
        self.cpu = ARM7TDMI(self)
        self.frame = bytes(240 * 160 * 3)

    # ---- mini-BIOS: reset pad + IRQ trampoline @ 0x18 ----
    # (clean-room, standard sequence per GBATEK: stack scratch regs,
    #  call the user handler at [0x03007FFC], restore, return)
    @staticmethod
    def _build_bios():
        bios = bytearray(0x4000)
        bios[0x18:0x1C] = (0xEA000008).to_bytes(4, "little")   # b 0x40
        irq = (0xE92D500F,      # stmfd sp!,{r0-r3,r12,lr}
               0xE3A00301,      # mov   r0,#0x04000000
               0xE28FE000,      # add   lr,pc,#0
               0xE510F004,      # ldr   pc,[r0,#-4]   ; [0x03FFFFFC]
               0xE8BD500F,      # ldmfd sp!,{r0-r3,r12,lr}
               0xE25EF004)      # subs  pc,lr,#4      ; restores cpsr
        for i, w in enumerate(irq):
            bios[0x40 + 4 * i:0x44 + 4 * i] = w.to_bytes(4, "little")
        return bios

    # ---- palette LUT: BGR555 -> RGB888 (optional blue-hue tint) ----
    def build_lut(self, hue):
        lut = []
        for c in range(32768):
            r5, g5, b5 = c & 31, (c >> 5) & 31, (c >> 10) & 31
            R = (r5 << 3) | (r5 >> 2)
            G = (g5 << 3) | (g5 >> 2)
            B = (b5 << 3) | (b5 >> 2)
            if hue:
                R = int(R * 0.68)
                G = int(G * 0.88)
                B = min(255, int(B * 1.02) + 30)
            lut.append(bytes((R, G, B)))
        return lut

    def set_hue(self, on):
        self.blue_hue = on
        self.lut = self.build_lut(on)

    def load(self, rom):
        self.rom = bytes(rom)
        pad = (-len(self.rom)) % 4
        padded = self.rom + b"\x00" * pad
        self.romw = array("I")
        self.romw.frombytes(padded)
        self.romh = array("H")
        self.romh.frombytes(padded)
        if sys.byteorder != "little":
            self.romw.byteswap()
            self.romh.byteswap()
        self.reset()

    def reset(self):
        for m in (self.ew, self.iw, self.io, self.pal, self.vram, self.oam):
            m[:] = bytes(len(m))
        self.cpu.reset()
        self.vblank = self.hblank = self.vcount = 0
        self.iflags = 0
        self.tre = [0] * 4
        self.tc = [0] * 4
        self.tacc = [0] * 4
        self.io[0x88:0x8A] = (0x200).to_bytes(2, "little")   # SOUNDBIAS
        self.io[0x300] = 1                                   # POSTFLG

    # =========================== bus ================================
    def _region(self, a):
        r = a >> 24
        if r == 2:  return self.ew, a & 0x3FFFF
        if r == 3:  return self.iw, a & 0x7FFF
        if r == 5:  return self.pal, a & 0x3FF
        if r == 6:
            o = a & 0x1FFFF
            if o >= 0x18000: o -= 0x8000
            return self.vram, o
        if r == 7:  return self.oam, a & 0x3FF
        if r == 0:  return self.bios, a & 0x3FFF
        if r in (0xE, 0xF): return self.sram, a & 0xFFFF
        return None, 0

    def read8(self, a):
        a &= M32
        r = a >> 24
        if r == 4:
            v = self.io_read(a & 0x3FE)
            return (v >> 8) & 0xFF if a & 1 else v & 0xFF
        if r == 0xD:                                    # EEPROM: "ready"
            return 1
        if 8 <= r <= 0xC:
            o = a & 0x1FFFFFF
            return self.rom[o] if o < len(self.rom) else 0
        m, o = self._region(a)
        return m[o] if m else 0

    def read16(self, a):
        a &= M32
        r = a >> 24
        if r == 4:
            return self.io_read(a & 0x3FE)
        if r == 0xD:
            return 1
        if 8 <= r <= 0xC:
            o = a & 0x1FFFFFE
            if o + 2 <= len(self.rom):
                return int.from_bytes(self.rom[o:o + 2], "little")
            return 0
        m, o = self._region(a)
        return int.from_bytes(m[o:o + 2], "little") if m else 0

    def read32(self, a):
        a &= M32
        r = a >> 24
        if r == 4:
            o = a & 0x3FC
            return self.io_read(o) | (self.io_read(o + 2) << 16)
        if r == 0xD:
            return 1
        if 8 <= r <= 0xC:
            o = a & 0x1FFFFFC
            if o + 4 <= len(self.rom):
                return int.from_bytes(self.rom[o:o + 4], "little")
            return 0
        m, o = self._region(a)
        return int.from_bytes(m[o:o + 4], "little") if m else 0

    def write8(self, a, v):
        a &= M32
        r = a >> 24
        if r == 4:
            self.io_write8(a & 0x3FF, v & 0xFF)
            return
        if r == 0 or 8 <= r <= 0xD:
            return                                      # bios/rom read-only
        m, o = self._region(a)
        if m is not None:
            m[o] = v & 0xFF

    def write16(self, a, v):
        a &= M32
        r = a >> 24
        if r == 4:
            self.io_write(a & 0x3FE, v & 0xFFFF)
            return
        if r == 0 or 8 <= r <= 0xD:
            return
        m, o = self._region(a)
        if m is not None:
            m[o:o + 2] = (v & 0xFFFF).to_bytes(2, "little")

    def write32(self, a, v):
        a &= M32
        r = a >> 24
        if r == 4:
            o = a & 0x3FC
            self.io_write(o, v & 0xFFFF)
            self.io_write(o + 2, (v >> 16) & 0xFFFF)
            return
        if r == 0 or 8 <= r <= 0xD:
            return
        m, o = self._region(a)
        if m is not None:
            m[o:o + 4] = (v & M32).to_bytes(4, "little")

    # =========================== IO ================================
    def io_read(self, off):
        if off == 0x130:                                # KEYINPUT
            return self.keys
        if off == 0x004:                                # DISPSTAT
            st = int.from_bytes(self.io[4:6], "little")
            vm = 4 if self.vcount == self.io[5] else 0
            return (st & 0xFFF8) | self.vblank | (self.hblank << 1) | vm
        if off == 0x006:                                # VCOUNT
            return self.vcount
        if off == 0x202:                                # IF
            return self.iflags
        if off in (0x100, 0x104, 0x108, 0x10C):         # timer counters
            return self.tc[(off - 0x100) >> 2] & 0xFFFF
        return int.from_bytes(self.io[off:off + 2], "little")

    def io_write8(self, off, v):
        if off == 0x202:
            self.iflags &= ~v & 0x3FFF
            return
        if off == 0x203:
            self.iflags &= ~(v << 8) & 0x3FFF
            return
        if off == 0x301:                                # HALTCNT
            self.cpu.halt = True
            return
        # widen to a 16-bit write so side effects still fire
        base = off & ~1
        cur = int.from_bytes(self.io[base:base + 2], "little")
        if off & 1:
            self.io_write(base, (cur & 0x00FF) | (v << 8))
        else:
            self.io_write(base, (cur & 0xFF00) | v)

    def io_write(self, off, v):
        if off == 0x202:                                # IF: write-1-to-clear
            self.iflags &= ~v & 0x3FFF
            return
        if off == 0x300:                                # POSTFLG / HALTCNT
            self.io[0x300] = v & 0xFF
            if v & 0x8000:
                self.cpu.halt = True
            return
        prev = int.from_bytes(self.io[off:off + 2], "little")
        self.io[off:off + 2] = (v & 0xFFFF).to_bytes(2, "little")
        if off in (0x200, 0x208):                       # IE / IME
            self.check_irq()
        elif off in (0xBA, 0xC6, 0xD2, 0xDE):           # DMAxCNT_H
            n = (off - 0xBA) // 12
            if v & 0x8000 and not prev & 0x8000:        # enable rising edge
                base = 0xB0 + 12 * n
                self.dsrc[n] = int.from_bytes(self.io[base:base + 4],
                                              "little") & 0x0FFFFFFF
                self.ddst[n] = int.from_bytes(self.io[base + 4:base + 8],
                                              "little") & 0x0FFFFFFF
                if (v >> 12) & 3 == 0:                  # immediate
                    self.dma_run(n)
        elif off in (0x100, 0x104, 0x108, 0x10C):       # timer reload
            self.tre[(off - 0x100) >> 2] = v & 0xFFFF
        elif off in (0x102, 0x106, 0x10A, 0x10E):       # timer control
            t = (off - 0x102) >> 2
            if v & 0x80 and not prev & 0x80:
                self.tc[t] = self.tre[t]
                self.tacc[t] = 0

    # ---- interrupts ----
    def raise_irq(self, n):
        self.iflags |= 1 << n
        self.check_irq()

    def check_irq(self):
        ie = int.from_bytes(self.io[0x200:0x202], "little")
        if ie & self.iflags:
            self.cpu.halt = False                       # halt wakes on IE&IF
            if self.io[0x208] & 1:
                self.cpu.irq()

    # ---- DMA ----
    def dma_trigger(self, timing):
        for n in range(4):
            cnt = int.from_bytes(self.io[0xBA + 12 * n:0xBC + 12 * n],
                                 "little")
            if cnt & 0x8000 and (cnt >> 12) & 3 == timing:
                self.dma_run(n)

    def dma_run(self, n):
        base = 0xB0 + 12 * n
        cnt = int.from_bytes(self.io[base + 10:base + 12], "little")
        count = int.from_bytes(self.io[base + 8:base + 10], "little")
        if count == 0:
            count = 0x10000 if n == 3 else 0x4000
        word = (cnt >> 10) & 1
        dmode = (cnt >> 5) & 3
        smode = (cnt >> 7) & 3
        sz = 4 if word else 2
        rd = self.read32 if word else self.read16
        wr = self.write32 if word else self.write16
        src = self.dsrc[n]
        dst = self.ddst[n]
        for _ in range(count):
            wr(dst & ~(sz - 1), rd(src & ~(sz - 1)))
            if smode == 0: src += sz
            elif smode == 1: src -= sz
            if dmode in (0, 3): dst += sz
            elif dmode == 1: dst -= sz
        self.dsrc[n] = src & M32
        if dmode == 3:                                  # inc + reload
            self.ddst[n] = int.from_bytes(self.io[base + 4:base + 8],
                                          "little") & 0x0FFFFFFF
        else:
            self.ddst[n] = dst & M32
        if cnt & 0x4000:
            self.raise_irq(8 + n)
        if not cnt & 0x200:                             # no repeat -> disable
            self.io[base + 11] &= 0x7F

    # ---- timers (per-scanline granularity, 1232 cycles/line) ----
    PRES = (1, 64, 256, 1024)

    def tick_timers(self, cycles=1232):
        ov_prev = 0
        for t in range(4):
            ctl = int.from_bytes(self.io[0x102 + 4 * t:0x104 + 4 * t],
                                 "little")
            if not ctl & 0x80:
                ov_prev = 0
                continue
            if ctl & 4:                                 # cascade
                inc = ov_prev
            else:
                self.tacc[t] += cycles
                p = self.PRES[ctl & 3]
                inc = self.tacc[t] // p
                self.tacc[t] %= p
            ov = 0
            if inc:
                c = self.tc[t] + inc
                while c > 0xFFFF:
                    c = self.tre[t] + (c - 0x10000)
                    ov += 1
                    if self.tre[t] == 0 and c > 0xFFFF and ov > 4:
                        c &= 0xFFFF
                        break
                self.tc[t] = c
                if ov and ctl & 0x40:
                    self.raise_irq(3 + t)
            ov_prev = ov

    # ---- one video frame: 228 scanlines (160 visible + 68 vblank) ----
    def run_frame(self):
        per = max(6, self.budget // 285)
        cpu = self.cpu
        io = self.io
        for line in range(228):
            self.vcount = line
            self.hblank = 0
            st = io[4]
            if line == 0:
                self.vblank = 0
            elif line == 160:
                self.vblank = 1
                self.frame = self.render()
                if st & 0x08:
                    self.raise_irq(0)                   # vblank IRQ
                self.dma_trigger(1)                     # vblank DMA
                cpu.halt = False                        # VBlankIntrWait wake
            if self.vcount == io[5] and st & 0x20:
                self.raise_irq(2)                       # vcount match IRQ
            cpu.run(per)
            self.hblank = 1
            if line < 160:
                if st & 0x10:
                    self.raise_irq(1)                   # hblank IRQ
                self.dma_trigger(2)                     # hblank DMA
            self.tick_timers()
            cpu.run(per >> 2)

    # ========================== PPU ================================
    # VBA-style whole-frame software rasterize at vblank:
    # text BGs (modes 0/1) + affine BGs (1/2) + bitmap (3/4/5) + OBJs
    OBJ_SIZES = {(0, 0): (8, 8),   (0, 1): (16, 16), (0, 2): (32, 32),
                 (0, 3): (64, 64), (1, 0): (16, 8),  (1, 1): (32, 8),
                 (1, 2): (32, 16), (1, 3): (64, 32), (2, 0): (8, 16),
                 (2, 1): (8, 32),  (2, 2): (16, 32), (2, 3): (32, 64)}

    def render(self):
        io = self.io
        dispcnt = io[0] | io[1] << 8
        if dispcnt & 0x80:                              # forced blank
            return b"\xff\xff\xff" * 38400
        mode = dispcnt & 7
        lut = self.lut
        pal = array("H")
        pal.frombytes(bytes(self.pal))
        if sys.byteorder != "little":
            pal.byteswap()
        pb_ = [lut[p & 0x7FFF] for p in pal]
        objs = dispcnt & 0x1000

        if mode == 3:
            px = array("H")
            px.frombytes(bytes(self.vram[:76800]))
            if sys.byteorder != "little":
                px.byteswap()
            fb = [lut[p & 0x7FFF] for p in px]
            if not objs:
                return b"".join(fb)
        elif mode == 4:
            base = 0xA000 if dispcnt & 0x10 else 0
            seg = self.vram[base:base + 38400]
            if not objs:
                return b"".join(map(pb_.__getitem__, seg))
            fb = [pb_[c] for c in seg]
        elif mode == 5:
            base = 0xA000 if dispcnt & 0x10 else 0
            px = array("H")
            px.frombytes(bytes(self.vram[base:base + 40960]))
            if sys.byteorder != "little":
                px.byteswap()
            fb = [pb_[0]] * 38400
            for y in range(128):
                ro = y * 240 + 40
                so = y * 160
                for x in range(160):
                    fb[ro + x] = lut[px[so + x] & 0x7FFF]
        elif mode <= 2:
            fb = [pb_[0]] * 38400                       # backdrop
            layers = []
            for n in range(4):
                if not dispcnt & (0x100 << n):
                    continue
                if mode == 0:
                    kind = "t"
                elif mode == 1:
                    kind = "t" if n < 2 else ("a" if n == 2 else None)
                else:
                    kind = "a" if n >= 2 else None
                if not kind:
                    continue
                layers.append((io[8 + 2 * n] & 3, n, kind))
            for prio in (3, 2, 1, 0):
                for p, n, k in sorted(layers, key=lambda t: -t[1]):
                    if p == prio:
                        if k == "t":
                            self.draw_text_bg(fb, n, pb_)
                        else:
                            self.draw_affine_bg(fb, n, pb_)
                if objs:
                    self.draw_obj(fb, prio, pb_, dispcnt)
            return b"".join(fb)
        else:
            return b"\x00\x08\x20" * 38400

        if objs:
            for prio in (3, 2, 1, 0):
                self.draw_obj(fb, prio, pb_, dispcnt)
        return b"".join(fb)

    def draw_text_bg(self, fb, n, pb_):
        io = self.io
        vram = self.vram
        cnt = io[8 + 2 * n] | io[9 + 2 * n] << 8
        charbase = ((cnt >> 2) & 3) * 0x4000
        depth8 = (cnt >> 7) & 1
        scrbase = ((cnt >> 8) & 0x1F) * 0x800
        size = (cnt >> 14) & 3
        w = 512 if size & 1 else 256
        h = 512 if size & 2 else 256
        hofs = (io[0x10 + 4 * n] | io[0x11 + 4 * n] << 8) & 0x1FF
        vofs = (io[0x12 + 4 * n] | io[0x13 + 4 * n] << 8) & 0x1FF
        cache = {}
        for y in range(160):
            sy = (y + vofs) & (h - 1)
            ty = sy >> 3
            py = sy & 7
            row = y * 240
            sx = hofs & (w - 1)
            x = 0
            while x < 240:
                tx = sx >> 3
                sb = scrbase
                txm, tym = tx, ty
                if tx >= 32:
                    sb += 0x800
                    txm = tx - 32
                if ty >= 32:
                    sb += 0x1000 if w == 512 else 0x800
                    tym = ty - 32
                o = sb + (tym * 32 + txm) * 2
                entry = vram[o] | vram[o + 1] << 8
                key = entry | py << 16
                rowpix = cache.get(key)
                if rowpix is None:
                    tile = entry & 0x3FF
                    hf = (entry >> 10) & 1
                    ry = 7 - py if entry & 0x800 else py
                    if depth8:
                        off = charbase + tile * 64 + ry * 8
                        if off + 8 <= 0x10000:
                            rowpix = [pb_[c] if c else None
                                      for c in vram[off:off + 8]]
                        else:
                            rowpix = [None] * 8
                    else:
                        pbank = (entry >> 12) & 0xF
                        off = charbase + tile * 32 + ry * 4
                        if off + 4 <= 0x10000:
                            base = pbank * 16
                            rowpix = []
                            for b in vram[off:off + 4]:
                                lo = b & 0xF
                                hi = b >> 4
                                rowpix.append(pb_[base + lo] if lo else None)
                                rowpix.append(pb_[base + hi] if hi else None)
                        else:
                            rowpix = [None] * 8
                    if hf:
                        rowpix = rowpix[::-1]
                    cache[key] = rowpix
                px = sx & 7
                nrun = 8 - px
                if nrun > 240 - x:
                    nrun = 240 - x
                fi = row + x
                for i in range(nrun):
                    c = rowpix[px + i]
                    if c is not None:
                        fb[fi + i] = c
                x += nrun
                sx = (sx + nrun) & (w - 1)

    def draw_affine_bg(self, fb, n, pb_):
        io = self.io
        vram = self.vram
        cnt = io[8 + 2 * n] | io[9 + 2 * n] << 8
        charbase = ((cnt >> 2) & 3) * 0x4000
        scrbase = ((cnt >> 8) & 0x1F) * 0x800
        wrap = (cnt >> 13) & 1
        sz = 128 << ((cnt >> 14) & 3)
        tpitch = sz >> 3
        rb = 0x20 if n == 2 else 0x30

        def s16(o):
            v = io[o] | io[o + 1] << 8
            return v - 0x10000 if v & 0x8000 else v

        def s28(o):
            v = (io[o] | io[o + 1] << 8 | io[o + 2] << 16 |
                 io[o + 3] << 24) & 0x0FFFFFFF
            return v - 0x10000000 if v & 0x08000000 else v

        pa, pb2 = s16(rb), s16(rb + 2)
        pc, pd = s16(rb + 4), s16(rb + 6)
        rx, ry = s28(rb + 8), s28(rb + 12)
        smask = sz - 1
        for y in range(160):
            cx = rx + pb2 * y
            cy = ry + pd * y
            row = y * 240
            for x in range(240):
                px = (cx + pa * x) >> 8
                py = (cy + pc * x) >> 8
                if wrap:
                    px &= smask
                    py &= smask
                elif not (0 <= px < sz and 0 <= py < sz):
                    continue
                t = vram[scrbase + (py >> 3) * tpitch + (px >> 3)]
                c = vram[charbase + t * 64 + (py & 7) * 8 + (px & 7)]
                if c:
                    fb[row + x] = pb_[c]

    def draw_obj(self, fb, prio, pb_, dispcnt):
        oam = self.oam
        vram = self.vram
        map1d = (dispcnt >> 6) & 1
        bitmap = (dispcnt & 7) >= 3
        for i in range(127, -1, -1):                    # low index on top
            o = i * 8
            a2 = oam[o + 4] | oam[o + 5] << 8
            if (a2 >> 10) & 3 != prio:
                continue
            a0 = oam[o] | oam[o + 1] << 8
            om = (a0 >> 8) & 3
            if om == 2:                                 # disabled
                continue
            a1 = oam[o + 2] | oam[o + 3] << 8
            wh = self.OBJ_SIZES.get(((a0 >> 14) & 3, (a1 >> 14) & 3))
            if not wh:
                continue
            w, h = wh
            x = a1 & 0x1FF
            y = a0 & 0xFF
            if x & 0x100:
                x -= 512
            if y >= 160:
                y -= 256
            affine = om & 1
            bw, bh = (w * 2, h * 2) if om == 3 else (w, h)
            if x + bw <= 0 or x >= 240 or y + bh <= 0 or y >= 160:
                continue
            depth8 = (a0 >> 13) & 1
            tile = a2 & 0x3FF
            pbank = (a2 >> 12) & 0xF
            if depth8:
                tile &= 0x3FE
            if affine:
                g = ((a1 >> 9) & 0x1F) * 32

                def sp(o2):
                    v = oam[g + o2] | oam[g + o2 + 1] << 8
                    return v - 0x10000 if v & 0x8000 else v

                pa, pb2, pc2, pd = sp(6), sp(14), sp(22), sp(30)
                hbw, hbh = bw >> 1, bh >> 1
                hw, hh = w >> 1, h >> 1
            else:
                hf = (a1 >> 12) & 1
                vf = (a1 >> 13) & 1
            if map1d:
                pitch = (w >> 3) * (2 if depth8 else 1)
            else:
                pitch = 32
            for dy in range(bh):
                sy = y + dy
                if sy < 0 or sy >= 160:
                    continue
                row = sy * 240
                for dx in range(bw):
                    sx = x + dx
                    if sx < 0 or sx >= 240:
                        continue
                    if affine:
                        tx = ((pa * (dx - hbw) + pb2 * (dy - hbh)) >> 8) + hw
                        ty2 = ((pc2 * (dx - hbw) + pd * (dy - hbh)) >> 8) + hh
                        if not (0 <= tx < w and 0 <= ty2 < h):
                            continue
                    else:
                        tx = w - 1 - dx if hf else dx
                        ty2 = h - 1 - dy if vf else dy
                    if depth8:
                        tn = (tile + (ty2 >> 3) * pitch +
                              (tx >> 3) * 2) & 0x3FF
                        if bitmap and tn < 512:
                            continue
                        c = vram[0x10000 + tn * 32 + (ty2 & 7) * 8 + (tx & 7)]
                        if c:
                            fb[row + sx] = pb_[256 + c]
                    else:
                        tn = (tile + (ty2 >> 3) * pitch + (tx >> 3)) & 0x3FF
                        if bitmap and tn < 512:
                            continue
                        b = vram[0x10000 + tn * 32 + (ty2 & 7) * 4 +
                                 ((tx & 7) >> 1)]
                        c = (b >> 4) if tx & 1 else (b & 0xF)
                        if c:
                            fb[row + sx] = pb_[256 + pbank * 16 + c]

# =====================================================================
#  VBA-style GUI  ·  blue on black  ·  60 fps loop
# =====================================================================

class App(tk.Tk):
    KEYMAP = {"up": 6, "down": 7, "left": 5, "right": 4,
              "z": 0, "x": 1, "return": 3, "shift_r": 2,
              "a": 9, "s": 8}

    def __init__(self):
        super().__init__()
        self.title("ac's gba emu")
        self.configure(bg=BLACK)
        self.resizable(False, False)

        self.gba = GBA()
        self.gba.load(build_demo_rom())
        self.rom_name = "meowdemo (built-in)"

        self.scale = tk.IntVar(value=2)
        self.paused = tk.BooleanVar(value=False)
        self.hue = tk.BooleanVar(value=True)
        self.skip = tk.IntVar(value=0)
        self._skipctr = 0
        self._fps = 0.0
        self._fpsn = 0
        self._fpst = time.perf_counter()
        self._imgref = None
        self._msg = ""
        self._msg_until = 0.0

        self._build_menu()

        self.canvas = tk.Canvas(self, width=480, height=320, bg=BLACK,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self.cimg = self.canvas.create_image(0, 0, anchor="nw")

        self.status = tk.Label(self, text="", anchor="w", bg=BLACK,
                               fg=BLUE, font=("Courier", 11), padx=6)
        self.status.pack(fill="x")

        self.bind("<KeyPress>", self._kd)
        self.bind("<KeyRelease>", self._ku)

        self._next = time.perf_counter()
        self.after(1, self._tick)

    # ---- VBA-style in-window menu strip ----
    # (self.config(menu=...) is broken for theming: on macOS the menus jump
    #  to the aqua system bar and ignore colors. so: a real strip inside
    #  the window — black frame, blue labels, click/hover posts dropdowns.)
    def _build_menu(self):
        kw = dict(bg=BLACK, fg=BLUE, activebackground=DKBLU,
                  activeforeground=BLUE, tearoff=0,
                  relief="flat", bd=0)

        self.menubar = tk.Frame(self, bg=BLACK)
        self.menubar.pack(fill="x", side="top")
        self._strip = []            # [(label_widget, menu)]

        mf = tk.Menu(self, **kw)
        mf.add_command(label="Open ROM…", accelerator="Ctrl+O",
                       command=self.open_rom)
        mf.add_command(label="Close ROM (back to meowdemo)",
                       command=self.load_demo)
        mf.add_separator()
        mf.add_checkbutton(label="Pause", accelerator="P",
                           variable=self.paused, selectcolor=BLUE)
        mf.add_command(label="Reset", accelerator="Ctrl+R",
                       command=self.reset)
        mf.add_command(label="Screenshot (.ppm)", command=self.screenshot)
        mf.add_separator()
        mf.add_command(label="Exit", command=self.destroy)
        self._add_strip("File", mf)

        mo = tk.Menu(self, **kw)
        mv = tk.Menu(mo, **kw)
        for s in (1, 2, 3):
            mv.add_radiobutton(label=f"{s}x ({240*s}x{160*s})",
                               variable=self.scale, value=s,
                               command=self._resize, selectcolor=BLUE)
        mo.add_cascade(label="Video Size", menu=mv)
        ms = tk.Menu(mo, **kw)
        for s in (0, 1, 2):
            ms.add_radiobutton(label=f"Frameskip {s}", variable=self.skip,
                               value=s, selectcolor=BLUE)
        mo.add_cascade(label="Frameskip", menu=ms)
        mo.add_checkbutton(label="Blue Hue", variable=self.hue,
                           command=lambda: self.gba.set_hue(self.hue.get()),
                           selectcolor=BLUE)
        self._add_strip("Options", mo)

        mh = tk.Menu(self, **kw)
        mh.add_command(label="About…", command=self.about)
        self._add_strip("Help", mh)

        self.bind("<Control-o>", lambda e: self.open_rom())
        self.bind("<Control-r>", lambda e: self.reset())
        self.bind("<p>", lambda e: self.paused.set(not self.paused.get()))
        if sys.platform == "darwin":
            self.bind("<Command-o>", lambda e: self.open_rom())
            self.bind("<Command-r>", lambda e: self.reset())

    def _add_strip(self, text, menu):
        lbl = tk.Label(self.menubar, text=text, bg=BLACK, fg=BLUE,
                       font=("Courier", 12), padx=10, pady=3, cursor="hand2")
        lbl.pack(side="left")
        lbl.bind("<Button-1>", lambda e, m=menu, w=lbl: self._post(w, m))
        lbl.bind("<Enter>", lambda e, w=lbl: w.config(bg=DKBLU))
        lbl.bind("<Leave>", lambda e, w=lbl: w.config(bg=BLACK))
        self._strip.append((lbl, menu))

    def _post(self, lbl, menu):
        lbl.config(bg=DKBLU)
        x = lbl.winfo_rootx()
        y = lbl.winfo_rooty() + lbl.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()
            lbl.config(bg=BLACK)
            # give keyboard back to the game — otherwise dpad dies
            # after any menu interaction (classic tk focus steal)
            self.after(10, self._refocus)

    def _refocus(self):
        try:
            self.focus_force()
        except tk.TclError:
            pass
        self.gba.keys = 0x3FF          # drop any stuck keys

    def _resize(self):
        s = self.scale.get()
        self.canvas.config(width=240 * s, height=160 * s)

    # ---- input ----
    def _kd(self, e):
        b = self.KEYMAP.get(e.keysym.lower())
        if b is not None:
            self.gba.keys &= ~(1 << b) & 0x3FF

    def _ku(self, e):
        b = self.KEYMAP.get(e.keysym.lower())
        if b is not None:
            self.gba.keys |= (1 << b)

    # ---- actions ----
    def open_rom(self):
        self.paused.set(True)                           # freeze while browsing
        self.update_idletasks()                         # macOS Tk dialog fix
        try:
            path = filedialog.askopenfilename(
                parent=self, title="Open GBA ROM",
                filetypes=[("GBA ROM", "*.gba *.agb *.bin *.zip"),
                           ("All files", "*")])
        except tk.TclError:
            path = filedialog.askopenfilename(parent=self)
        if not path:
            self.paused.set(False)
            self._refocus()
            return
        try:
            rom = self._read_rom(path)
            if not rom:
                raise ValueError("file is empty / no ROM inside the zip")
            if len(rom) > 32 * 1024 * 1024:
                raise ValueError("bigger than 32 MB — not a GBA cart")
            self.gba.load(rom)
            self.rom_name = path.replace("\\", "/").split("/")[-1]
            self.title(f"ac's gba emu - {self.rom_name}")
            gt = self._header_title(rom)
            self.flash(f"loaded {self.rom_name}"
                       + (f"   [{gt}]" if gt else ""))
        except (OSError, ValueError) as e:
            messagebox.showerror("ac's gba emu", f"couldn't load ROM:\n{e}")
        self.paused.set(False)
        self._refocus()

    def _read_rom(self, path):
        if path.lower().endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist()
                         if n.lower().endswith((".gba", ".agb", ".bin"))]
                if not names:
                    names = [n for n in z.namelist() if not n.endswith("/")]
                if not names:
                    return b""
                return z.read(names[0])
        with open(path, "rb") as f:
            return f.read()

    @staticmethod
    def _header_title(rom):
        # cart header: game title @ 0xA0..0xAB, game code @ 0xAC..0xAF
        if len(rom) < 0xB0:
            return ""
        t = rom[0xA0:0xAC].rstrip(b"\x00").decode("ascii", "replace").strip()
        c = rom[0xAC:0xB0].rstrip(b"\x00").decode("ascii", "replace").strip()
        return f"{t} {c}".strip()

    def load_demo(self):
        self.gba.load(build_demo_rom())
        self.rom_name = "meowdemo (built-in)"
        self.title("ac's gba emu")
        self.paused.set(False)
        self._refocus()

    def reset(self):
        self.gba.reset()
        self.gba.keys = 0x3FF
        self._refocus()

    def flash(self, text, secs=3.0):
        self._msg = text
        self._msg_until = time.perf_counter() + secs
        self.status.config(text=f" {text}")

    def screenshot(self):
        fn = f"acgba_shot_{int(time.time())}.ppm"
        try:
            with open(fn, "wb") as f:
                f.write(b"P6\n240 160\n255\n" + self.gba.frame)
            self.flash(f"saved {fn}")
        except OSError as e:
            messagebox.showerror("ac's gba emu", str(e))

    def about(self):
        messagebox.showinfo(
            "About ac's gba emu",
            "ac's gba emu 0.2\nTeam Flames / Samsoft\n\n"
            "single-file python GBA emulator\n"
            "ARM7TDMI + Thumb · IRQ/DMA/timers · tile+sprite+bitmap PPU\n"
            "clean-room, GBATEK docs only\n\nmeow · nya")

    # ---- 60 fps main loop ----
    def _tick(self):
        t0 = time.perf_counter()
        if not self.paused.get():
            self.gba.run_frame()
            emu_dt = time.perf_counter() - t0
            # adaptive instruction budget — hold the frame under ~10 ms
            if emu_dt < 0.008:
                self.gba.budget = min(400000, int(self.gba.budget * 1.08) + 64)
            elif emu_dt > 0.012:
                self.gba.budget = max(3000, int(self.gba.budget * 0.90))

            self._skipctr += 1
            if self._skipctr > self.skip.get():
                self._skipctr = 0
                img = tk.PhotoImage(data=b"P6\n240 160\n255\n" + self.gba.frame)
                s = self.scale.get()
                if s > 1:
                    img = img.zoom(s)
                self.canvas.itemconfig(self.cimg, image=img)
                self._imgref = img

            self._fpsn += 1
            now = time.perf_counter()
            if now - self._fpst >= 0.5:
                self._fps = self._fpsn / (now - self._fpst)
                self._fpsn = 0
                self._fpst = now
                if now < self._msg_until:
                    self.status.config(text=f" {self._msg}")
                else:
                    self.status.config(
                        text=f" {self.rom_name}   {self._fps:5.1f} fps   "
                             f"budget {self.gba.budget}")
        else:
            self.status.config(text=f" {self.rom_name}   [paused]")

        # pace to 60 fps
        self._next += 1 / 60
        now = time.perf_counter()
        if self._next < now - 0.25:                     # fell behind, resync
            self._next = now
        delay = max(1, int((self._next - now) * 1000))
        self.after(delay, self._tick)


if __name__ == "__main__":
    App().mainloop()
