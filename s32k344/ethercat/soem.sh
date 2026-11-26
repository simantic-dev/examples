#!/usr/bin/env bash
# Fetch SOEM (EtherCAT MainDevice, GPLv2 with linking exception) at a pinned tag into the gitignored soem/ next to this
# script and apply the Zephyr raw-socket patch (AF_PACKET NIC driver, soem-zephyr.patch, GPLv2 like SOEM). Prints the dir.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HERE/soem"
if [ ! -d "$DIR" ]; then
  git clone -q --depth 1 --branch v1.4.0 https://github.com/OpenEtherCATsociety/SOEM.git "$DIR"
  git -C "$DIR" apply "$HERE/soem-zephyr.patch"
fi
echo "$DIR"
