#!/usr/bin/env bash
# Commit updated data (data/, state/) with retries against concurrent pushes.
# When a run waited in the queue, the previous run has already pushed its own regenerated data: both runs then
# changed the same generated files and the rebase conflicts. Each such file keeps this run's version (the newer
# computation); files this run did not touch keep the remote's version, as before.
set -euo pipefail
git config user.name "forte-markets-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add data state 2>/dev/null || true
if git diff --cached --quiet; then echo "no data changes"; exit 0; fi
git commit -q -m "data: $1 $(date -u +%Y-%m-%dT%H:%MZ)"

in_rebase() { [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; }
sync() {
  git pull --rebase -q origin main && return 0
  in_rebase || return 1
  for _ in 1 2 3 4 5; do
    for f in $(git diff --name-only --diff-filter=U); do
      echo "conflict in $f: keeping this run's version"
      if git checkout --theirs -- "$f" 2>/dev/null; then git add -- "$f"; else git rm -q -- "$f"; fi
    done
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || true
    in_rebase || return 0
  done
  git rebase --abort || true
  return 1
}
for i in 1 2 3; do
  if sync && git push -q origin HEAD:main; then echo "pushed"; exit 0; fi
  sleep $((i * 5))
done
echo "::error::push failed after 3 attempts"; exit 1
