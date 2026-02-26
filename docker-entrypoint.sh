#!/bin/sh
# docker-entrypoint.sh — runs as root, fixes volume ownership, then drops to appuser.
# Idempotent: safe to re-run on every container start.
set -e

# Ensure the /data directory exists and is owned by the application user.
# This is required for HashRegistry to write hash_registry.json on the named volume.
mkdir -p /data
chown -R appuser:appuser /data

exec gosu appuser "$@"
