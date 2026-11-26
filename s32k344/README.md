# S32K344 Ethernet (NXP MR-CANHUBK344)

Two runnable setups for the S32K344's Ethernet MAC on the `mr_canhubk3` board, both on stock Zephyr. Nothing here is
firmware we wrote for the simulator: `udp-echo` is Zephyr's own `samples/net/sockets/echo_server`, and `ethercat` is
SOEM, the open-source EtherCAT MainDevice, on Zephyr raw sockets.

Needs `sim` 0.10.11 or newer (`sim update`), a Zephyr workspace (`west`, `ZEPHYR_BASE`) and the Zephyr SDK.
Run everything from the root of this repo.

## udp-echo: stock Zephyr networking

```sh
s32k344/udp-echo/build.sh
sim run --scenario s32k344/udp-echo/scenario.yaml --ascii
```

The board comes up at 192.0.2.1, the scripted host at 192.0.2.2 (`udp-echo/peer.py`) resolves it with ARP and sends
five UDP datagrams to port 4242; each must come back unchanged. Expected: `Network connected` on the console and
`[host] eth: RESULT: PASS`.

## ethercat: S32K344 as an EtherCAT MainDevice

```sh
s32k344/ethercat/build.sh      # fetches SOEM v1.4.0 into ethercat/soem and patches it for Zephyr
sim run --scenario s32k344/ethercat/scenario.yaml --ascii
```

SOEM finds three EtherCAT SubDevices chained in a ring (`ethercat/peer_sub1..3.py`, all on
`peers/eth/ethercat_sub.py`), maps their process data, takes them to OP and runs 200 cycles of LRW at 1 ms, checking
the working counter and that each SubDevice echoes its outputs. Expected:
`ecat: slaves 3`, `ecat: cycles 200 ok 200 lost 0 badwkc 0 echo_err 0`, `ecat: RESULT: PASS`.
Edit a `peer_subN.py` to inject faults: `drop_every`/`drop_after` loses frames, `stuck_safeop` keeps a SubDevice out
of OP with an AL status code; the MainDevice reports both.

## How it is wired

- `peers.board` in each setup adds the board's NXP TJA1103 100BASE-T1 PHY as a Python peer on the MAC's MDIO bus
  (`phy: Network.ScriptedMdioPhy @ emac 0x12`, `peers/eth/tja1103.py`, clause 45). Without it the stock board
  config stops at boot with `Unable to obtain PHY ID`. Any other PHY is a different Python file at its MDIO address.
- The hosts and SubDevices are `Network.ScriptedEthernetPeer`s on the scenario's `type: eth` medium: they get every
  frame with `on_frame` and send with `ctx.send`.
- Every frame on the wire is written to `udp-echo.pcap` / `ethercat.pcap` next to the scenario, for Wireshark.

## What is and is not modelled

The S32K344 EMAC (Synopsys DWC EQOS) is checked register by register against the S32K3XX reference manual ch.75:
both Tx/Rx queues and DMA channels, receive routing, the RM reset values, checksum offload, MDIO clause 22 and 45,
software reset and the MC_ME clock gate. Not modelled: TSN (PTP, time-aware gates, frame preemption, credit-based
shaping), the MMC statistics counters, MII/RMII select and half duplex. Timing is modelled, not measured on silicon,
and the peers are transaction level (no electrical layer). Frames between two simulated machines are delivered at
scenario quantum boundaries (10 us by default), not at their exact wire time.
