# ST LIS2DW12 accelerometer as a scripted I2C peer (7-bit 0x18 with SA0 low,
# 0x19 high), with the data-ready / FIFO interrupt on INT1. Wire INT1 with the
# part's `irq:` key (scenario.yaml) and the firmware's EXTI line sees it.
# Register file, 8-bit pointer, auto-increment (CTRL2.IF_ADD_INC, on at reset).
# A write arrives as [reg] then [data...] in one or two on_write calls and
# on_finish at STOP: accumulate, byte 0 is the pointer.
#
# Timing follows what the firmware programs: while CTRL1.ODR is not 0 the part
# takes one sample every 1/ODR (a periodic timer). In bypass mode a sample
# lands in OUT_X..Z and sets STATUS.DRDY; reading OUT_Z_H clears it. With
# FIFO_CTRL.FMODE set, samples queue in a 32-deep FIFO instead and each 6-byte
# read from OUT_X_L pops one. INT1 follows CTRL4 (DRDY, FIFO threshold, FIFO
# full) and CTRL3.H_LACTIVE.
# Source: ST lis2dw12-pid lis2dw12_reg.h (github.com/STMicroelectronics/
# lis2dw12-pid @ b1885c23a228): register addresses, bit fields, ODR and FMODE codes.
#
# MODELED SIMPLIFICATION: single-data-conversion-on-demand mode (CTRL1.MODE=2),
# tap / free-fall / wake-up / 6D detection, INT2, latched vs pulsed DRDY
# (CTRL7.DRDY_PULSED), BDU, filters, temperature and self-test are not modelled.
# Low-power and high-performance modes run at the same ODR; resolution is 14 bit
# in high-performance mode and 12 bit otherwise (low bits read 0).
ACCEL_G = (0.0, 0.0, 1.0)  # the world: board at rest, +Z up

WHO_AM_I_ID = 0x44
ODR_HZ = (0, 12.5, 12.5, 25, 50, 100, 200, 400, 800, 1600)  # CTRL1.ODR code 0..9 (code 1 is 1.6 Hz in low-power only)
FS_G = (2, 4, 8, 16)                                       # CTRL6.FS
FIFO_DEPTH = 32
BYPASS, FIFO, STREAM_TO_FIFO, BYPASS_TO_STREAM, STREAM = 0, 1, 3, 4, 6  # FIFO_CTRL.FMODE

WHO_AM_I, CTRL1, CTRL2, CTRL3, CTRL4, CTRL5, CTRL6 = 0x0F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25
STATUS, OUT_X_L, OUT_Z_H, FIFO_CTRL, FIFO_SAMPLES, CTRL7 = 0x27, 0x28, 0x2D, 0x2E, 0x2F, 0x3F
RESET = {CTRL1: 0, CTRL2: 0x04, CTRL3: 0, CTRL4: 0, CTRL5: 0, CTRL6: 0, FIFO_CTRL: 0, CTRL7: 0}


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ptr = 0
        self.buf = b""
        self.int1 = None
        self._reset()

    def _reset(self):
        self.regs = dict(RESET)
        self.out = bytes(6)
        self.drdy = False
        self.fifo = []
        self.ovr = False
        self.ctx.cancel_timer()
        self._update_int1()

    def _sample(self):
        fs = FS_G[(self.regs[CTRL6] >> 4) & 3]
        keep = 0xFFFC if (self.regs[CTRL1] >> 2) & 3 == 1 else 0xFFF0  # 14 or 12 bit, left-aligned
        out = b""
        for g in ACCEL_G:
            raw = max(-32768, min(32767, round(g * 32768 / fs)))
            out += ((raw & 0xFFFF) & keep).to_bytes(2, "little")
        return out

    def _fth(self):
        return len(self.fifo) >= (self.regs[FIFO_CTRL] & 0x1F)

    def _update_int1(self):
        c4 = self.regs[CTRL4]
        level = bool((c4 & 1 and self.drdy) or (c4 & 2 and self.fifo and self._fth())
                     or (c4 & 4 and len(self.fifo) == FIFO_DEPTH))
        level ^= bool(self.regs[CTRL3] & 0x08)  # H_LACTIVE: active low
        if level != self.int1:
            self.int1 = level
            self.ctx.gpio(0).set(level)

    def _rearm(self):
        odr = ODR_HZ[min(self.regs[CTRL1] >> 4, 9)]
        if odr:
            self.ctx.schedule_periodic(round(1e6 / odr))
        else:
            self.ctx.cancel_timer()

    def on_timer(self):
        s = self._sample()
        mode = self.regs[FIFO_CTRL] >> 5
        if mode == BYPASS:
            self.out, self.drdy = s, True
        elif len(self.fifo) < FIFO_DEPTH:
            self.fifo.append(s)
        elif mode == FIFO:
            self.ovr = True                      # full: FIFO mode stops collecting
        else:
            self.fifo, self.ovr = self.fifo[1:] + [s], True  # stream modes drop the oldest
        self._update_int1()

    def on_write(self, data):
        data = bytes(data)
        if not self.buf and data:                # first byte of the transaction: the pointer
            self.ptr, self.buf, data = data[0], data[:1], data[1:]
        for v in data:
            self._write(self.ptr, v)
            if self.regs[CTRL2] & 0x04:
                self.ptr += 1

    def _write(self, reg, v):
        if reg not in RESET:
            return
        if reg == CTRL2 and v & 0x40:            # SOFT_RESET
            self._reset()
            return
        self.regs[reg] = v
        if reg == CTRL1:
            self._rearm()
        if reg == FIFO_CTRL and v >> 5 == BYPASS:  # bypass empties the FIFO
            self.fifo, self.ovr = [], False
        self._update_int1()

    def on_finish(self):
        self.buf = b""

    def _byte(self, reg):
        if reg == WHO_AM_I:
            return WHO_AM_I_ID
        if reg == STATUS:
            return self.drdy | (bool(self.fifo) and self._fth()) << 7
        if reg == FIFO_SAMPLES:
            return len(self.fifo) | self.ovr << 6 | (bool(self.fifo) and self._fth()) << 7
        if OUT_X_L <= reg <= OUT_Z_H:
            return self.out[reg - OUT_X_L]
        return self.regs.get(reg, 0)

    def on_read(self, count):
        self.buf = b""
        out = bytearray()
        for _ in range(count):
            if self.ptr == OUT_X_L and self.regs[FIFO_CTRL] >> 5 != BYPASS and self.fifo:
                self.out = self.fifo.pop(0)
                self.ovr = False
            out.append(self._byte(self.ptr))
            if self.ptr == OUT_Z_H:
                self.drdy = False
            if self.regs[CTRL2] & 0x04:
                self.ptr = OUT_X_L if self.ptr == OUT_Z_H and self.regs[FIFO_CTRL] >> 5 != BYPASS else self.ptr + 1
        self._update_int1()
        return bytes(out)
