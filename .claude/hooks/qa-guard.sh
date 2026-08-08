#!/usr/bin/env bash
# Thin wrapper so settings files reference a stable path (spec §5 G5).
exec python3 "$(dirname "${BASH_SOURCE[0]}")/qa-guard.py"
