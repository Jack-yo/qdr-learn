#!/usr/bin/env bash
# Install a user-level systemd timer. Does not store Alpaca secrets.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then PYTHON="$(command -v python3)"; fi
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/qdr-l1-v3.service" <<EOF
[Unit]
Description=QDR L1 V3 research-only daily update
[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$PYTHON -m quant_research.workflow.l1_v3_pipeline --root "$ROOT" daily
TimeoutStartSec=3600
EOF
cat > "$UNIT_DIR/qdr-l1-v3.timer" <<'EOF'
[Unit]
Description=Check QDR L1 V3 research every 30 minutes
[Timer]
OnCalendar=*-*-* *:00,30:00
Persistent=true
Unit=qdr-l1-v3.service
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now qdr-l1-v3.timer
echo "User timer installed: systemctl --user status qdr-l1-v3.timer"
echo "Verify: $PYTHON -m quant_research.workflow.l1_v3_verify --root \"$ROOT\" --live"
echo "Headless hosts may require explicitly enabling systemd user lingering."
