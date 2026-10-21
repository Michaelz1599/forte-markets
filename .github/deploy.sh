#!/usr/bin/env bash
# Deploy the site + Worker to Cloudflare. Creates the KV namespace on the first run.
# Needs: CLOUDFLARE_API_TOKEN, optional CLOUDFLARE_ACCOUNT_ID, EDITOR_CODE.
set -uo pipefail
api=https://api.cloudflare.com/client/v4
auth=(-H "Authorization: Bearer $CLOUDFLARE_API_TOKEN")
acc="$(printf '%s' "${CLOUDFLARE_ACCOUNT_ID:-}" | tr -d '[:space:]\342\200\217\342\200\216' | tr 'A-F' 'a-f')"
if ! [[ "$acc" =~ ^[0-9a-f]{32}$ ]]; then
  echo "::warning title=CLOUDFLARE_ACCOUNT_ID::not a 32-hex id; using the token's account"
  acc=$(curl -s "${auth[@]}" "$api/accounts" | python3 -c 'import json,sys;print(json.load(sys.stdin)["result"][0]["id"])')
fi
export CLOUDFLARE_ACCOUNT_ID="$acc"

# KV namespace: find it by title, create it if missing
title="forte-markets-kv"
kv=$(curl -s "${auth[@]}" "$api/accounts/$acc/storage/kv/namespaces?per_page=100" |
     python3 -c "import json,sys;d=json.load(sys.stdin);print(next((n['id'] for n in d.get('result') or [] if n['title']=='$title'),''))")
if [ -z "$kv" ]; then
  resp=$(curl -s -X POST "${auth[@]}" -H "Content-Type: application/json" --data "{\"title\":\"$title\"}" "$api/accounts/$acc/storage/kv/namespaces")
  kv=$(echo "$resp" | python3 -c 'import json,sys;d=json.load(sys.stdin);print((d.get("result") or {}).get("id",""))')
  if [ -z "$kv" ]; then
    echo "::error title=KV namespace::could not create: $(echo "$resp" | head -c 400)"; exit 1
  fi
  echo "::notice title=KV namespace::created $kv"
fi

if [ -z "${EDITOR_CODE:-}" ]; then
  echo "::warning title=EDITOR_CODE::secret missing - editing on the site is disabled until it is set"
  hash="0000000000000000000000000000000000000000000000000000000000000000"
else
  hash=$(printf '%s' "$EDITOR_CODE" | sha256sum | cut -d' ' -f1)
fi
python3 - "$kv" "$hash" <<'PY'
import json, re, sys
src = open("wrangler.jsonc", encoding="utf-8").read()
src = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("//"))
cfg = json.loads(src.replace("__KV_ID__", sys.argv[1]).replace("__EDITOR_HASH__", sys.argv[2]))
json.dump(cfg, open("wrangler.generated.json", "w"), indent=1)
PY

out=$(npx --yes wrangler@4.147.0 deploy --config wrangler.generated.json 2>&1); rc=$?
if [ $rc -ne 0 ] && echo "$out" | grep -q "register a workers.dev subdomain"; then
  for name in "forte-iem" "forte-markets-$(date +%s | tail -c 5)"; do
    resp=$(curl -s -X PUT "${auth[@]}" -H "Content-Type: application/json" --data "{\"subdomain\":\"$name\"}" "$api/accounts/$acc/workers/subdomain")
    echo "$resp" | grep -q '"success":true' && break
  done
  out=$(npx --yes wrangler@4.147.0 deploy --config wrangler.generated.json 2>&1); rc=$?
fi
echo "$out"
url=$(echo "$out" | grep -oE 'https://[a-zA-Z0-9.-]+\.workers\.dev' | head -1)
mkdir -p state && printf '{"url":"%s","deployedAt":"%s","ok":%s}\n' "${url}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$([ $rc -eq 0 ] && echo true || echo false)" > state/deploy.json
if [ $rc -ne 0 ]; then
  msg=$(echo "$out" | grep -vE '^\s*$' | grep -viE 'npm (warn|notice)' | tail -12 | sed 's/%/%25/g' | sed ':a;N;$!ba;s/\n/%0A/g')
  echo "::error title=wrangler deploy failed::${msg}"
  exit $rc
fi
echo "::notice title=dashboard deployed::${url:-deployed}"
