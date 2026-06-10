#!/bin/bash
# Render the launchd plist template with this machine's local paths
# and install it to ~/Library/LaunchAgents/. Idempotent: safe to re-run.
#
# Usage:  ./install.sh
#
# After running, also configure pmset to wake the Mac before 6am:
#   sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00
#
# To uninstall, run ./install.sh uninstall.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$PROJECT_DIR/com.newsagent.plist.template"
INSTANCE="$PROJECT_DIR/com.newsagent.plist"
LABEL="com.newsagent.daily"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

uninstall() {
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        launchctl bootout "$DOMAIN/$LABEL" || true
        echo "Bootout: $DOMAIN/$LABEL"
    fi
    rm -f "$LAUNCH_AGENT" "$INSTANCE"
    echo "Removed launchd plist."
}

if [ "${1:-}" = "uninstall" ]; then
    uninstall
    exit 0
fi

if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: template not found: $TEMPLATE" >&2
    exit 1
fi

# Render template with current paths.
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__USER_HOME__|$HOME|g" \
    "$TEMPLATE" > "$INSTANCE"

plutil -lint "$INSTANCE" >/dev/null

# Configure git to push via a dedicated passphraseless deploy key, bypassing
# the ssh-agent and keychain. Without this, the unattended 6am push breaks
# after every reboot (the agent's in-memory copy of the passphrase-protected
# personal key is wiped on restart). See the 2026-05-25 reboot incident.
DEPLOY_KEY="$HOME/.ssh/news_agent_deploy"
if [ -f "$DEPLOY_KEY" ]; then
    git -C "$PROJECT_DIR" config core.sshCommand \
        "ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o IdentityAgent=none"
    echo "git core.sshCommand -> $DEPLOY_KEY (agent/keychain-independent)"
else
    echo "WARNING: deploy key $DEPLOY_KEY missing. Automated push will fail."
    echo "  Generate:  ssh-keygen -t ed25519 -f $DEPLOY_KEY -N '' -C news-agent-automation"
    echo "  Then add $DEPLOY_KEY.pub as a WRITE-enabled deploy key on the GitHub repo,"
    echo "  and re-run ./install.sh."
fi

# Install (replace any prior version).
mkdir -p "$HOME/Library/LaunchAgents"
ln -sf "$INSTANCE" "$LAUNCH_AGENT"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "$DOMAIN/$LABEL" || true
fi
launchctl bootstrap "$DOMAIN" "$LAUNCH_AGENT"

echo "Installed: $LAUNCH_AGENT -> $INSTANCE"
echo "Status:"
launchctl print "$DOMAIN/$LABEL" | grep -E '^\s*(state|path|program)' | sed 's/^/  /'
echo
echo "NEXT: configure Mac to wake at 5:55am daily (one-time, requires sudo):"
echo "  sudo pmset repeat wakeorpoweron MTWRFSU 05:55:00"
echo
echo "To run manually NOW (full pipeline incl. git push):"
echo "  launchctl kickstart -p $DOMAIN/$LABEL"
echo
echo "To uninstall:"
echo "  ./install.sh uninstall"
