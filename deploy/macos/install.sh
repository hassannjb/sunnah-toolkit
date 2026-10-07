#!/bin/bash
# Install (or reinstall) LaunchDaemons from this directory. Needs sudo.
#   sudo deploy/macos/install.sh api tunnel           # named-tunnel setup
#   sudo deploy/macos/install.sh api ngrok ssh-tunnel # no-domain setup
#   sudo deploy/macos/install.sh --remove ngrok       # stop + uninstall
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

if [ "${1:-}" = "--remove" ]; then
  shift
  for s in "$@"; do
    label="com.sunnah-toolkit.$s"
    launchctl bootout "system/$label" 2>/dev/null || true
    rm -f "/Library/LaunchDaemons/$label.plist"
    echo "removed $label"
  done
  exit 0
fi

here="$(cd "$(dirname "$0")" && pwd)"
user="${SUDO_USER:?run via sudo from your own account}"
home="$(dscl . -read "/Users/$user" NFSHomeDirectory | awk '{print $2}')"
services=("$@")
[ ${#services[@]} -gt 0 ] || { echo "name the services to install, e.g.: api tunnel" >&2; exit 1; }

for s in "${services[@]}"; do
  label="com.sunnah-toolkit.$s"
  dest="/Library/LaunchDaemons/$label.plist"
  sed -e "s|__USER__|$user|g" -e "s|__HOME__|$home|g" "$here/$label.plist" > "$dest"
  chown root:wheel "$dest"; chmod 644 "$dest"
  launchctl bootout "system/$label" 2>/dev/null || true
  launchctl bootstrap system "$dest"
  echo "loaded $label"
done
