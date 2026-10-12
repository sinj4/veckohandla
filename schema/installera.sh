#!/bin/sh
# Installerar veckokörningen (macOS launchd) för den här katalogen.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents/se.veckohandla.plist"
mkdir -p "$DIR/data"
sed -e "s|__DIR__|$DIR|g" -e "s|__HOME__|$HOME|g" "$DIR/schema/se.veckohandla.plist.template" > "$DEST"
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"
echo "Installerat: $DEST (körs måndagar 06:30)"
