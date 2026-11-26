#!/usr/bin/env bash
# Build Zephyr's own samples/net/sockets/echo_server, unmodified, for mr_canhubk3 (S32K344).
# Needs a Zephyr workspace (west, ZEPHYR_BASE) and the Zephyr SDK. Output: s32k344/udp-echo/build/zephyr/zephyr.elf
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
west build -b mr_canhubk3 "${ZEPHYR_BASE:?set ZEPHYR_BASE}/samples/net/sockets/echo_server" -d "$HERE/build" --pristine
