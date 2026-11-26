# A host on the Ethernet segment at a fixed IP, as a scripted Ethernet peer (Network.ScriptedEthernetPeer): it
# answers ARP for its address and receives and sends UDP, so firmware with a static address (any subnet) has
# something to talk to without a DHCP server or the engine's 10.0.2.x gateway.
# Answers ICMP echo requests (ping). Frame level only: no other ICMP, no TCP, no IP fragments, no VLAN tags. IPv4 header options are skipped, the UDP
# checksum is checked when present and always written. Addresses are dotted strings.
#
# Use: exec this file in your peer script, then subclass `UdpHost`:
#     exec(compile(open("peers/eth/udp_host.py").read(), "peers/eth/udp_host.py", "exec"))
#     class Peer(UdpHost):
#         IP = "192.168.7.10"
#         def on_udp(self, src_ip, src_port, dst_port, data):
#             self.send_udp(src_ip, src_port, dst_port, b"pong " + data)
import struct

ETH_ARP, ETH_IPV4 = 0x0806, 0x0800
BROADCAST = b"\xff" * 6


def _ip(s):
    return bytes(int(x) for x in s.split("."))


def _ip_str(b):
    return ".".join(str(x) for x in b)


def checksum(data):
    """The Internet checksum (RFC 1071) of `data`."""
    if len(data) & 1:
        data += b"\0"
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def udp_frame(src_mac, dst_mac, src_ip, dst_ip, src_port, dst_port, data):
    """Ethernet + IPv4 + UDP frame with both checksums, as bytes from the destination MAC onward."""
    udp_len = 8 + len(data)
    pseudo = _ip(src_ip) + _ip(dst_ip) + struct.pack("!BBH", 0, 17, udp_len)
    udp = struct.pack("!HHHH", src_port, dst_port, udp_len, 0) + data
    ck = checksum(pseudo + udp) or 0xFFFF
    udp = udp[:6] + struct.pack("!H", ck) + udp[8:]
    ip = struct.pack("!BBHHHBBH", 0x45, 0, 20 + udp_len, 0, 0x4000, 64, 17, 0) + _ip(src_ip) + _ip(dst_ip)
    ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
    return dst_mac + src_mac + struct.pack("!H", ETH_IPV4) + ip + udp


def parse_udp(frame):
    """(src_ip, dst_ip, src_port, dst_port, data) of an IPv4 UDP frame, or None if it is not a good one."""
    if len(frame) < 14 + 20 + 8 or struct.unpack("!H", frame[12:14])[0] != ETH_IPV4:
        return None
    ip = frame[14:]
    ihl = (ip[0] & 0xF) * 4
    total = struct.unpack("!H", ip[2:4])[0]
    if ip[0] >> 4 != 4 or ihl < 20 or ip[9] != 17 or total > len(ip) or checksum(ip[:ihl]) != 0:
        return None
    if struct.unpack("!H", ip[6:8])[0] & 0x3FFF:
        return None  # a fragment
    udp = ip[ihl:total]
    sport, dport, length, ck = struct.unpack("!HHHH", udp[:8])
    if length < 8 or length > len(udp):
        return None
    udp = udp[:length]
    if ck and checksum(ip[12:20] + struct.pack("!BBH", 0, 17, length) + udp) != 0:
        return None
    return _ip_str(ip[12:16]), _ip_str(ip[16:20]), sport, dport, udp[8:]


class UdpHost:
    IP = "192.168.7.10"

    def __init__(self, ctx):
        self.ctx = ctx
        self.mac = bytes(int(b, 16) for b in ctx.mac.split(":"))
        self.arp = {}  # IP -> MAC of the hosts that have asked for us or sent to us

    def on_frame(self, frame):
        data = frame["bytes"]
        eth = struct.unpack("!H", data[12:14])[0] if len(data) >= 14 else 0
        if eth == ETH_ARP and len(data) >= 42:
            op, sha, spa, tpa = struct.unpack("!H", data[20:22])[0], data[22:28], data[28:32], data[38:42]
            self.arp[_ip_str(spa)] = sha
            if op == 1 and tpa == _ip(self.IP):
                self.ctx.send(sha + self.mac + struct.pack("!H", ETH_ARP) + struct.pack("!HHBBH", 1, ETH_IPV4, 6, 4, 2)
                              + self.mac + _ip(self.IP) + sha + spa)
            return
        if len(data) >= 14 + 20 + 8 and eth == ETH_IPV4 and data[23] == 1 and data[30:34] == _ip(self.IP):
            ihl = (data[14] & 0xF) * 4
            icmp = data[14 + ihl:14 + struct.unpack("!H", data[16:18])[0]]
            if icmp[0] == 8 and checksum(data[14:14 + ihl]) == 0 and checksum(icmp) == 0:  # echo request
                self.arp[_ip_str(data[26:30])] = data[6:12]
                reply = b"\0\0" + b"\0\0" + icmp[4:]
                reply = reply[:2] + struct.pack("!H", checksum(reply)) + reply[4:]
                ip = struct.pack("!BBHHHBBH", 0x45, 0, 20 + len(reply), 0, 0x4000, 64, 1, 0) + _ip(self.IP) + data[26:30]
                ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
                self.ctx.send(data[6:12] + self.mac + struct.pack("!H", ETH_IPV4) + ip + reply)
            return
        u = parse_udp(data)
        if u and u[1] in (self.IP, "255.255.255.255"):
            self.arp[u[0]] = data[6:12]
            self.on_udp(u[0], u[2], u[3], u[4])

    def on_udp(self, src_ip, src_port, dst_port, data):
        """Override: a datagram for this host arrived."""

    def send_udp(self, dst_ip, dst_port, src_port, data):
        mac = self.arp.get(dst_ip)
        if mac is None:
            self.ctx.warning("no ARP entry for %s: a host has to talk to us first" % dst_ip)
            return
        self.ctx.send(udp_frame(self.mac, mac, self.IP, dst_ip, src_port, dst_port, bytes(data)))
