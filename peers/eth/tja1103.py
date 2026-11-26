# NXP TJA1103 100BASE-T1 PHY on an MDIO bus, as a scripted MDIO PHY (Network.ScriptedMdioPhy @ <mac> <address>).
# Transaction level: the registers Zephyr's phy_tja1103 driver reads and writes, no electrical effects.
# Clause 22 reads the PHY identifier (0x1BB013, TJA1103_ID); clause 45 MMD 30 holds the vendor registers
# (DEVICE_CONTROL 0x0040, PHY_CONTROL 0x8100, PHY_STATUS 0x8102, always-accessible 0x801F, functional IRQ
# 0x80A0-0x80A2) and MMD 1 the BASE-T1 PMA control (0x0834, master/slave). Registers the driver does not touch
# read as written (0 at reset); the 0x8102 link bit follows virtual time.
#
# Use: `file: peers/eth/tja1103.py` brings the link up at once. To choose when, exec this file in your peer script, then subclass `Tja1103`:
#     exec(compile(open("peers/eth/tja1103.py").read(), "peers/eth/tja1103.py", "exec"))
#     class Peer(Tja1103):
#         LINK_UP_NS = 50_000_000      # link comes up 50 ms into the run; None keeps it down
ID1, ID2 = 0x001B, 0xB013
MMD_PMAPMD, MMD_VENDOR1 = 1, 30
BT1_CTRL = 0x0834
PHY_STATUS, LINK_STAT = 0x8102, 1 << 2
ALWAYS_ACCESSIBLE, FUSA_PASS_IRQ = 0x801F, 1 << 4


class Tja1103:
    LINK_UP_NS = 0

    def __init__(self, ctx):
        self.ctx = ctx
        self.regs = {(MMD_VENDOR1, ALWAYS_ACCESSIBLE): FUSA_PASS_IRQ}  # startup self test passed
        self.link_logged = False

    def link_up(self):
        return self.LINK_UP_NS is not None and self.ctx.now_ns >= self.LINK_UP_NS

    def mdio_read(self, devad, reg):
        if devad is None:
            return {2: ID1, 3: ID2}.get(reg, 0)
        if (devad, reg) == (MMD_VENDOR1, PHY_STATUS):
            if self.link_up() and not self.link_logged:
                self.link_logged = True
                self.ctx.info("link up")
            return LINK_STAT if self.link_up() else 0
        return self.regs.get((devad, reg), 0)

    def mdio_write(self, devad, reg, value):
        if devad is None or (devad, reg) == (MMD_VENDOR1, PHY_STATUS):
            return
        if (devad, reg) == (MMD_VENDOR1, ALWAYS_ACCESSIBLE):  # write 1 to clear
            value = self.regs.get((devad, reg), 0) & ~value
        self.regs[(devad, reg)] = value & 0xFFFF


Peer = Tja1103
