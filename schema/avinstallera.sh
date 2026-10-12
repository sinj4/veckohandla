#!/bin/sh
# Tar bort veckokörningen (macOS launchd). Rör inte data/, config eller inloggningen.
set -e
DEST="$HOME/Library/LaunchAgents/se.veckohandla.plist"
if [ -f "$DEST" ]; then
  launchctl unload "$DEST" 2>/dev/null || true
  rm "$DEST"
  echo "Avinstallerat: $DEST"
else
  echo "Inget schema installerat ($DEST finns inte)"
fi
