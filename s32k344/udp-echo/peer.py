# ruff: noqa: F821
# Host 192.0.2.2 for the stock Zephyr echo_server (192.0.2.1:4242). Sends UDP datagrams (ARP resolves first)
# and judges that each comes back unchanged: `eth: RESULT: PASS|FAIL`.
exec(compile(open("peers/eth/udp_host.py").read(), "peers/eth/udp_host.py", "exec"))

DUT, PORT, N = "192.0.2.1", 4242, 5


class Peer(UdpHost):
    IP = "192.0.2.2"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.sent, self.got = 0, 0
        ctx.schedule_periodic(500_000)  # us: the DUT is up well before this

    def on_timer(self):
        if self.sent >= N + 3:
            self.ctx.cancel_timer()
            self.ctx.error("eth: RESULT: FAIL %d of %d datagrams echoed" % (self.got, N))
        elif self.got < N:
            if DUT not in self.arp:  # ARP request for the DUT, then UDP once it answers
                self.ctx.send(b"\xff" * 6 + self.mac + b"\x08\x06" + b"\0\x01\x08\0\x06\x04\0\x01" + self.mac
                              + bytes([192, 0, 2, 2]) + b"\0" * 6 + bytes([192, 0, 2, 1]))
            else:
                self.send_udp(DUT, PORT, 5000 + self.got, b"hello %d" % self.got)
            self.sent += 1

    def on_udp(self, src_ip, src_port, dst_port, data):
        if src_ip == DUT and src_port == PORT and data == b"hello %d" % self.got:
            self.got += 1
            self.ctx.info("eth: echo %d ok" % self.got)
            if self.got == N:
                self.ctx.cancel_timer()
                self.ctx.info("eth: RESULT: PASS")
