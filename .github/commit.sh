#!/usr/bin/env bash
# Commit updated data (data/, state/) with retries against concurrent pushes.
set -euo pipefail
git config user.name "forte-markets-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add data state 2>/dev/null || true
if git diff --cached --quiet; then echo "no data changes"; exit 0; fi
git commit -q -m "data: $1 $(date -u +%Y-%m-%dT%H:%MZ)"
for i in 1 2 3; do
  if git pull --rebase -q && git push -q; then echo "pushed"; exit 0; fi
  sleep $((i * 5))
done
echo "::error::push failed after 3 attempts"; exit 1
