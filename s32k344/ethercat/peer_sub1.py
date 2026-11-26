# ruff: noqa: SIM115, S102
# SubDevice 1 of 3 in the ring: DUT -> sub1 -> sub2 -> sub3 -> DUT (peers/eth/ethercat_sub.py).
CONFIG = {
    "mac": "02:00:00:00:EC:01",
    "upstream": "01:01:01:01:01:01",
    "vendor": 0x0000059D,
    "product": 0x510001,
    "out_sz": 4,
    "in_sz": 4,
    "forward_delay_ns": 500,
    "downstream": "02:00:00:00:EC:02",
}
exec(compile(open("peers/eth/ethercat_sub.py").read(), "peers/eth/ethercat_sub.py", "exec"))
