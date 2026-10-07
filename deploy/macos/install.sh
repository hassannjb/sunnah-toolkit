#!/bin/bash
# Install (or reinstall) LaunchDaemons from this directory. Needs sudo.
#   sudo deploy/macos/install.sh                 # api + ssh-tunnel (+ ngrok if present)
#   sudo deploy/macos/install.sh api             # just one
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

here="$(cd "$(dirname "$0")" && pwd)"
user="${SUDO_USER:?run via sudo from your own account}"
home="$(dscl . -read "/Users/$user" NFSHomeDirectory | awk '{print $2}')"
services=("$@")
[ ${#services[@]} -gt 0 ] || services=(api ssh-tunnel $([ -f "$here/com.sunnah-toolkit.ngrok.plist" ] && echo ngrok))

for s in "${services[@]}"; do
  label="com.sunnah-toolkit.$s"
  dest="/Library/LaunchDaemons/$label.plist"
  sed -e "s|__USER__|$user|g" -e "s|__HOME__|$home|g" "$here/$label.plist" > "$dest"
  chown root:wheel "$dest"; chmod 644 "$dest"
  launchctl bootout "system/$label" 2>/dev/null || true
  launchctl bootstrap system "$dest"
  echo "loaded $label"
done
