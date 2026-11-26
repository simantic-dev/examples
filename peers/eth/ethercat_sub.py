# EtherCAT SubDevice (ESC) for ScriptedEthernetPeer, the mirror of ethercat_main.py: transaction level, no bit timing.
# N copies chain into a ring on one `eth` medium (a hub), so each hop is a unicast frame: a SubDevice takes only frames from
# `upstream`, processes every datagram, and forwards the frame to `downstream` (its source MAC is its own). The last one
# (no `downstream`) sends it back to the MainDevice as a broadcast, the only frame the MainDevice's MAC accepts.
# Attach with a shim that sets CONFIG and exec()s this file (peers/README.md), one shim per SubDevice.
#
# CONFIG keys:
#   mac, upstream        this SubDevice's MAC and the MAC it accepts frames from (the MainDevice's, or the previous one's)
#   downstream           next SubDevice's MAC; absent on the last one of the chain
#   vendor, product      SII identity
#   out_sz, in_sz        process data bytes (SM2 outputs at 0x1000, SM3 inputs at 0x1100)
#   echo                 True: inputs follow outputs byte for byte, one frame later (default); False: inputs stay `in_fill`
#   in_fill              input byte when echo is off
#   forward_delay_ns     ESC forwarding delay per hop (rounded up to 1 us; 0 = none)
#   stuck_safeop         True: refuses OP, AL status SAFEOP + error, code `stuck_code`
#   stuck_code           AL status code reported (default 0x001B)
#   drop_every, drop_after   drop every `drop_every`th frame carrying a logical command once `drop_after` have passed
import struct

ETYPE = 0x88A4
APRD, APWR, APRW, FPRD, FPWR, FPRW, BRD, BWR, BRW, LRD, LWR, LRW = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
AL_INIT, AL_PREOP, AL_SAFEOP, AL_OP, AL_ERR, AL_ACK = 1, 2, 4, 8, 0x10, 0x10
RAM = 0x1000
SM_OUT, SM_IN = 0x1000, 0x1100
BCAST = "FF:FF:FF:FF:FF:FF"


def mac_bytes(s):
    return bytes(int(x, 16) for x in s.split(":"))


def sii_image(c):
    """SII words: identity at 0x08, mailbox-less config area, then strings, general, SyncM, TxPDO, RxPDO categories."""
    w = [0] * 0x40
    for i, v in enumerate((c["vendor"], c["product"], 0, 0)):
        w[8 + 2 * i], w[9 + 2 * i] = v & 0xFFFF, v >> 16
    cat = lambda t, body: [t, len(body)] + body
    pack = lambda b: list(struct.unpack(f"<{(len(b) + 1) // 2}H", bytes(b) + b"\0" * (len(b) % 2)))
    name = b"SIM-ESC"
    w += cat(10, pack(bytes([1, len(name)]) + name))
    w += cat(30, pack(bytes([0, 0, 0, 1]) + bytes(28)))
    sms = bytes(16) + struct.pack("<HHBBBB", SM_OUT, c["out_sz"], 0x64, 0, 1, 3) + struct.pack("<HHBBBB", SM_IN, c["in_sz"], 0x20, 0, 1, 4)
    w += cat(41, pack(sms))
    for t, pdo, sm, entry, n in ((51, 0x1600, 2, 0x7000, c["out_sz"]), (50, 0x1A00, 3, 0x6000, c["in_sz"])):
        b = struct.pack("<HBBBBH", pdo, n, sm, 0, 0, 0)
        for k in range(n):  # one 8-bit entry per byte
            b += struct.pack("<HBBBBH", entry, k + 1, 0, 6, 8, 0)
        w += cat(t, pack(b))
    w.append(0xFFFF)
    return w


class Peer:
    def __init__(self, ctx):
        c = self.c = CONFIG  # noqa: F821  set by the fixture's shim
        self.ctx = ctx
        self.mem = bytearray(0x2000)
        self.sii = sii_image(c)
        self.up, self.down = c["upstream"].upper(), c.get("downstream")
        self.mac = mac_bytes(c["mac"])
        self.mem[0:8] = bytes([0x11, 0, 0, 0, 8, 8, 8, 0x0F])  # type, rev, build, FMMUs, SMs, RAM KB, port descriptor
        self.mem[8:10] = struct.pack("<H", 0x01CC)
        self.mem[0x110:0x112] = struct.pack("<H", 0x0A30 if self.down else 0x0610)  # link + comm (and loop closed on the last)
        self.mem[0x502:0x504] = struct.pack("<H", 0)
        self.mem[SM_IN:SM_IN + c["in_sz"]] = bytes([c.get("in_fill", 0)]) * c["in_sz"]
        self.al_status(AL_INIT, 0)
        self.out_seen = self.echo_pending = False
        self.frames = self.lrw_frames = self.dropped = 0
        self.q = []  # (due_us, frame)
        self.delay_us = -(-c.get("forward_delay_ns", 0) // 1000)

    # --- register hooks
    def al_status(self, state, code):
        self.mem[0x130:0x132] = struct.pack("<H", state)
        self.mem[0x134:0x136] = struct.pack("<H", code)

    def al_control(self):
        req = self.mem[0x120] & 0x0F
        cur = self.mem[0x130] & 0x0F
        sm_out, sm_in = (struct.unpack_from("<HH", self.mem, 0x0800 + 8 * n)[1] for n in (2, 3))
        err = 0
        if req not in (1, 2, 4, 8):
            err = 0x0012
        elif req > cur and req != cur * 2:
            err = 0x0011  # no skipping states upward
        elif req == AL_SAFEOP and cur == AL_PREOP:
            err = 0x001D if sm_out != self.c["out_sz"] else 0x001E if sm_in != self.c["in_sz"] else 0
        elif req == AL_OP and (self.c.get("stuck_safeop") or not self.out_seen):
            err = self.c.get("stuck_code", 0x001B)
        if err:
            self.al_status(cur | AL_ERR, err)
        else:
            self.al_status(req, 0)

    def eeprom(self):
        cmd = (self.mem[0x503] >> 0) & 0x07
        adr = struct.unpack_from("<I", self.mem, 0x504)[0]
        if cmd == 1:
            words = [self.sii[a] if a < len(self.sii) else 0 for a in (adr, adr + 1)]
            self.mem[0x508:0x50C] = struct.pack("<2H", *words)
        self.mem[0x503] &= 0x7F  # not busy

    def wrote(self, a, n):
        hit = lambda lo, hi: a < hi and a + n > lo
        if hit(0x120, 0x122):
            self.al_control()
        if hit(0x502, 0x504):
            self.eeprom()
        if hit(SM_OUT, SM_OUT + self.c["out_sz"]):
            self.out_seen = True
            self.echo_pending = self.c.get("echo", True)

    def put(self, a, data):
        end = a + len(data)
        for lo, hi in ((0, 0x10), (0x110, 0x112), (0x130, 0x138), (0x508, 0x50C)):  # read-only: write accepted, ignored
            if a < hi and end > lo:
                return
        self.mem[a:end] = data
        self.wrote(a, len(data))

    def fmmus(self):
        for n in range(8):
            lo, ln, _sb, _eb, ph, _pb, typ, act = struct.unpack_from("<IHBBHBBB", self.mem, 0x600 + 16 * n)
            if act & 1 and ln:
                yield lo, ln, ph, typ

    # --- datagram engine
    def datagram(self, cmd, adp, ado, data):
        """Returns (new adp, data, wkc increment)."""
        n, wkc = len(data), 0
        read, write = cmd in (APRD, FPRD, BRD, APRW, FPRW, BRW), cmd in (APWR, FPWR, BWR, APRW, FPRW, BRW)
        if cmd in (APRD, APWR, APRW, BRD, BWR, BRW):
            hit = cmd >= BRD or adp == 0
            nadp = (adp + 1) & 0xFFFF
        elif cmd in (FPRD, FPWR, FPRW):
            hit, nadp = adp == struct.unpack_from("<H", self.mem, 0x10)[0], adp
        elif cmd in (LRD, LWR, LRW):
            log = adp | ado << 16
            out = bytearray(data)
            for lo, ln, ph, typ in self.fmmus():
                a, b = max(lo, log), min(lo + ln, log + n)
                if a >= b:
                    continue
                p = ph + (a - lo)
                if typ & 1 and cmd != LWR:
                    out[a - log:b - log] = self.mem[p:p + b - a]
                    wkc |= 1
                if typ & 2 and cmd != LRD:
                    self.mem[p:p + b - a] = data[a - log:b - log]
                    self.wrote(p, b - a)
                    wkc |= 2
            return adp, bytes(out), wkc
        else:
            return adp, data, 0
        if not hit or ado + n > len(self.mem) or ado < 0:
            return nadp, data, 0
        out = bytes(self.mem[ado:ado + n])
        if cmd in (BRD, BRW):  # a broadcast read ORs every SubDevice's bytes into the datagram
            out = bytes(x | y for x, y in zip(out, data))
        if write:
            self.put(ado, bytes(data))
        return nadp, out if read else data, (1 if read else 0) + (2 if write else 0)

    def on_frame(self, frame):
        if frame["ethertype"] != ETYPE or frame["src"].upper() != self.up or frame["dst"].upper() not in (BCAST, self.c["mac"].upper()):
            return
        b = bytearray(frame["bytes"])
        pos, logical = 16, False
        while pos + 12 <= len(b):
            cmd, _idx, adp, ado, ln, _irq = struct.unpack_from("<BBHHHH", b, pos)
            n = ln & 0x7FF
            logical |= cmd >= LRD
            adp2, data, inc = self.datagram(cmd, adp, ado, bytes(b[pos + 10:pos + 10 + n]))
            struct.pack_into("<H", b, pos + 2, adp2)
            b[pos + 10:pos + 10 + n] = data
            w = struct.unpack_from("<H", b, pos + 10 + n)[0]
            struct.pack_into("<H", b, pos + 10 + n, (w + inc) & 0xFFFF)
            pos += 12 + n
            if not ln & 0x8000:
                break
        if self.echo_pending:  # the application copies outputs to inputs between frames: the echo is one cycle late
            m = min(self.c["out_sz"], self.c["in_sz"])
            self.mem[SM_IN:SM_IN + m] = self.mem[SM_OUT:SM_OUT + m]
            self.echo_pending = False
        self.frames += 1
        if logical:
            self.lrw_frames += 1
            d = self.c.get("drop_every")
            if d and self.lrw_frames > self.c.get("drop_after", 0) and (self.lrw_frames - self.c.get("drop_after", 0)) % d == 0:
                self.dropped += 1
                self.ctx.info(f"ecat-sub {self.c['mac']}: dropped logical frame {self.lrw_frames} ({self.dropped} dropped)")
                return
        dst = mac_bytes(self.down) if self.down else b"\xff" * 6
        out = bytes(dst + self.mac + struct.pack(">H", ETYPE) + b[14:])
        if not self.delay_us:
            self.ctx.send(out)
            return
        self.q.append((self.ctx.now_us + self.delay_us, out))
        self.ctx.schedule_oneshot(self.delay_us)

    def on_timer(self):
        now = self.ctx.now_us
        while self.q and self.q[0][0] <= now:
            self.ctx.send(self.q.pop(0)[1])
        if self.q:
            self.ctx.schedule_oneshot(max(1, self.q[0][0] - now))
