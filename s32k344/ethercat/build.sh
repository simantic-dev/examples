#!/usr/bin/env bash
# Build SOEM + this EtherCAT MainDevice app for mr_canhubk3 (S32K344, stock Zephyr board config).
# Needs a Zephyr workspace (west, ZEPHYR_BASE) and the Zephyr SDK. Output: s32k344/ethercat/build/zephyr/zephyr.elf
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
west build -b mr_canhubk3 "$HERE" -d "$HERE/build" --pristine -- -DSOEM_DIR="$("$HERE/soem.sh")"
