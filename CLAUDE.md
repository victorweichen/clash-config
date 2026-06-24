# CLAUDE.md — EdNovas Clash Config Repo

This repo holds a customized version of an EdNovas subscription config (`EdNovasCloud_clash.yaml`).
The file is synced to a GitHub Gist which both devices pull from via Clash Verge's "Update" button.

---

## Architecture

```
Source of truth:  ~/clash-verge-ednovas/profiles/EdNovasCloud_clash.yaml  (Mac)
Git mirror:       ~/clash-config-repo/EdNovasCloud_clash.yaml              (this repo)
Gist:             gist.github.com/victorweichen/763389e1fe30b3ae79f3a75f37b4ca61
                  file: EdNovasCloud_clash_new.yaml
Active configs (read by mihomo at runtime — NOT the same as the source profile):
  Mac:    ~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml
  Lenovo: %APPDATA%\io.github.clash-verge-rev.clash-verge-rev\clash-verge.yaml
```

---

## Workflow: Making and Deploying a Config Change

### Step 1 — Edit source profile (Mac)
```
~/clash-verge-ednovas/profiles/EdNovasCloud_clash.yaml
```
This is the canonical source. Make all edits here.

### Step 2 — Sync to git repo
```bash
cp ~/clash-verge-ednovas/profiles/EdNovasCloud_clash.yaml ~/clash-config-repo/EdNovasCloud_clash.yaml
cd ~/clash-config-repo
git add EdNovasCloud_clash.yaml
git commit -m "describe change"
git push
```

### Step 3 — Update Gist (ALWAYS do this together with git push)
Use the GitHub token from git credential store:
```bash
TOKEN=$(printf "host=github.com\nprotocol=https\n" | git credential fill | grep password | cut -d= -f2)
python3 -c "
import urllib.request, json
token = '$TOKEN'
gist_id = '763389e1fe30b3ae79f3a75f37b4ca61'
filename = 'EdNovasCloud_clash_new.yaml'
with open('EdNovasCloud_clash.yaml') as f:
    content = f.read()
data = json.dumps({'files': {filename: {'content': content}}}).encode()
req = urllib.request.Request(
    f'https://api.github.com/gists/{gist_id}',
    data=data, method='PATCH',
    headers={'Authorization': f'token {token}', 'Content-Type': 'application/json'}
)
urllib.request.urlopen(req)
print('Gist updated')
"
```

### Step 4 — Pull on each device
On both Mac and Lenovo, open Clash Verge → click **Update** on the EdNovas profile.
This pulls from the Gist and regenerates `clash-verge.yaml`.

### Step 5 (optional) — Patch active config for immediate effect without restart
If you need the change live immediately without waiting for a full profile update,
patch `clash-verge.yaml` directly on each device, then reload via API.

**CRITICAL POLICY: Never push (steps 2–3) without explicit user confirmation ("可以" / "上传" / "确认").**
Always stop after step 1, report what changed, and wait.

---

## Device Access

### Mac
- mihomo API: Unix socket at `/tmp/verge/verge-mihomo.sock`
- Query connections: `curl -s --unix-socket /tmp/verge/verge-mihomo.sock http://localhost/connections`
- Query rules: `curl -s --unix-socket /tmp/verge/verge-mihomo.sock http://localhost/rules`
- Reload config: `curl -s -X PUT --unix-socket /tmp/verge/verge-mihomo.sock 'http://localhost/configs'`
- Active config: `~/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml`

### Lenovo (Windows)
- Tailscale IP: `100.103.10.73`
- SSH: `ssh -i ~/.ssh/id_lenovo victo@100.103.10.73`
- mihomo API: `http://100.103.10.73:9090` (bound to 0.0.0.0, all interfaces)
- API auth: `Authorization: Bearer set-your-secret`
- Query connections: `curl -s -H "Authorization: Bearer set-your-secret" http://100.103.10.73:9090/connections`
- Active config: `%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\clash-verge.yaml`
- External controller enabled via `verge.yaml`: `enable_external_controller: true`

### Mac mini (home server, used as US exit node)
- Tailscale IP: `100.95.126.121`
- SSH: `ssh vicfel@100.95.126.121`
- Runs gost SOCKS5 proxy on port 1080 (exits via Tailscale)
- Referenced in config as node `🏠 家庭宽带美国` (type: socks5, server: 100.95.126.121, port: 1080, interface-name: utun4)

---

## Patching clash-verge.yaml Directly (Immediate Effect)

Use this when you need a rule change to take effect right now without a full Clash Verge profile update.

### Mac — Python patch example
```python
import re
with open('/Users/victorchen/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml') as f:
    content = f.read()
# Insert DOMAIN rule before an IP-CIDR rule it must precede
content = content.replace(
    "- IP-CIDR,13.32.0.0/15,EdNovas云,no-resolve",
    "- DOMAIN-SUFFIX,example.com,DIRECT\n    - IP-CIDR,13.32.0.0/15,EdNovas云,no-resolve"
)
with open('/Users/victorchen/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml', 'w') as f:
    f.write(content)
```
Then reload: `curl -s -X PUT --unix-socket /tmp/verge/verge-mihomo.sock 'http://localhost/configs'`

### Lenovo — PowerShell patch via SSH
```powershell
$path = "$env:APPDATA\io.github.clash-verge-rev.clash-verge-rev\clash-verge.yaml"
$content = Get-Content $path -Raw -Encoding UTF8
$content = $content -replace "- IP-CIDR,13\.32\.0\.0/15,EdNovas云,no-resolve", "- DOMAIN-SUFFIX,example.com,DIRECT`n    - IP-CIDR,13.32.0.0/15,EdNovas云,no-resolve"
Set-Content $path $content -Encoding UTF8 -NoNewline
Stop-Process -Name "verge-mihomo" -Force -ErrorAction SilentlyContinue
```
Copy script to Lenovo via SCP, run via SSH:
```bash
scp -i ~/.ssh/id_lenovo /tmp/patch.ps1 victo@100.103.10.73:C:/Users/victo/patch.ps1
ssh -i ~/.ssh/id_lenovo victo@100.103.10.73 "powershell -ExecutionPolicy Bypass -File C:/Users/victo/patch.ps1"
```

---

## Rule Ordering — Critical

Clash evaluates rules **top to bottom, first match wins**.

**Problem:** Many `IP-CIDR,x.x.x.x/x,EdNovas云,no-resolve` rules near the end of the file catch
domains by their resolved IP before a DOMAIN rule can match them — even if the DOMAIN rule appears
earlier in the file, because `no-resolve` skips DNS and matches the raw IP in the packet.

**Rule:** Any `DOMAIN-SUFFIX` / `DOMAIN-KEYWORD` rule for a domain that belongs to an IP range
covered by an `IP-CIDR,...,no-resolve` rule **must be inserted BEFORE that IP-CIDR block**.

**Key IP-CIDR blocks to watch (near end of rules section):**
```
IP-CIDR,13.32.0.0/15,EdNovas云,no-resolve    ← slackb.com was caught here (AWS CloudFront)
IP-CIDR,18.208.0.0/13,EdNovas云,no-resolve   ← slackb.com also covered here
GEOIP,US,🇺🇲 美国节点                         ← catches anything resolving to a US IP
MATCH,漏网之鱼                                ← final catch-all
```

**Rule insertion anchor points:**
- Before `IP-CIDR,13.32.0.0/15` block: insert domain rules for AWS-hosted services (Slack, etc.)
- Before `GEOIP,US`: insert domain rules for US-hosted services not in other IP-CIDR blocks
- Before `MATCH,漏网之鱼`: last resort for anything else

---

## Customizations Added (vs Original EdNovas Profile)

### Proxy Groups Added
| Group | Type | Purpose |
|-------|------|---------|
| `OpenRouter` | select | Routes openrouter.ai; choices: 自动选择/中国以外/🇺🇲 美国节点/🇺🇲 美国Gemini |
| `🇺🇲 美国节点+tailnet` | url-test | US nodes + Mac mini home broadband |
| `🇺🇲 Gemini+tailnet` | url-test | Gemini-capable US nodes + Mac mini |

### Node Added
- `🏠 家庭宽带美国`: SOCKS5 via Mac mini Tailscale (100.95.126.121:1080, interface-name: utun4)

### Proxy Group Tuning
- 自动选择 / 中国以外: filtered out high-multiplier nodes (≥1.0X), added `lazy: false`, `interval: 1800`, `tolerance: 20`
- 美国Gemini: uses 美国23 + 美国4 + 美国9 (tested working)
- Health check URLs: changed from `gstatic.com/generate_204` → `http://1.1.1.1/` (more GFW-resilient)
- DNS: split into `nameserver` (CN DoH only) + `fallback` (overseas DoH/DoT) with `fallback-filter` geoip:CN

### DIRECT Rules Added (all to bypass VPN)
```yaml
# Tailscale — must be DIRECT or Tailscale traffic loops through VPN
DOMAIN-SUFFIX,tailscale.com,DIRECT
DOMAIN-SUFFIX,tailscale.io,DIRECT
DOMAIN-SUFFIX,tailscale.net,DIRECT

# Microsoft telemetry / Office config — no need to go through VPN
DOMAIN-SUFFIX,events.data.microsoft.com,DIRECT
DOMAIN-SUFFIX,ecs.office.com,DIRECT
DOMAIN-SUFFIX,activity.windows.com,DIRECT
DOMAIN-SUFFIX,config.office.com,DIRECT
DOMAIN-SUFFIX,microsoftpersonalcontent.com,DIRECT

# OneDrive / SkyDrive — large file sync, save VPN quota
DOMAIN-KEYWORD,1drv,DIRECT
DOMAIN-KEYWORD,onedrive,DIRECT
DOMAIN-KEYWORD,skydrive,DIRECT
DOMAIN-SUFFIX,onedrive.com,DIRECT
DOMAIN-SUFFIX,onedrive.live.com,DIRECT
DOMAIN-SUFFIX,storage.live.com,DIRECT
DOMAIN-SUFFIX,photos.live.com,DIRECT
DOMAIN-SUFFIX,livefilestore.com,DIRECT
DOMAIN-SUFFIX,oneclient.sfx.ms,DIRECT
DOMAIN-SUFFIX,skydrive.wns.windows.com,DIRECT
DOMAIN-SUFFIX,spoprod-a.akamaihd.net,DIRECT
DOMAIN-SUFFIX,storage.msn.com,DIRECT

# Windows Update — large downloads, save VPN quota
DOMAIN-SUFFIX,windowsupdate.com,DIRECT
DOMAIN-SUFFIX,update.microsoft.com,DIRECT
DOMAIN-SUFFIX,delivery.mp.microsoft.com,DIRECT
DOMAIN-SUFFIX,dl.delivery.mp.microsoft.com,DIRECT
DOMAIN-SUFFIX,download.windowsupdate.com,DIRECT

# AV / misc
DOMAIN-SUFFIX,sadownload.mcafee.com,DIRECT

# Work tools — accessed from China, no need for VPN
DOMAIN-SUFFIX,slackb.com,DIRECT      # inserted BEFORE IP-CIDR,13.32.0.0/15 block
DOMAIN-SUFFIX,datadoghq.com,DIRECT
```

### Rules Removed
- `RULE-SET,us-domain` (http ruleset) — was broken/failing, removed

---

## Monitoring Traffic

### Mac — check what's going through VPN vs DIRECT
```bash
curl -s --unix-socket /tmp/verge/verge-mihomo.sock http://localhost/connections | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for c in data.get('connections',[]):
  meta=c.get('metadata',{})
  print(f\"{c.get('rule','?')} | {c.get('chains',['?'])[0]} | {meta.get('host','?')} | ↓{c.get('download',0)//1024}KB ↑{c.get('upload',0)//1024}KB\")
"
```

### Lenovo — via API
```bash
curl -s -H "Authorization: Bearer set-your-secret" http://100.103.10.73:9090/connections | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)
for c in data.get('connections',[]):
  meta=c.get('metadata',{})
  print(f\"{c.get('rule','?')} | {c.get('chains',['?'])[0]} | {meta.get('host','?')} | ↓{c.get('download',0)//1024}KB ↑{c.get('upload',0)//1024}KB\")
"
```

---

## Pending Rule Suggestions (observed in monitoring, not yet added)

These were seen going through VPN and are candidates for DIRECT routing:

| Domain | Seen on | Process | Why candidate |
|--------|---------|---------|---------------|
| `mp.microsoft.com` | Lenovo | svchost | kv601/disc601 subdomains hit GeoIP:US repeatedly |
| `login.live.com` | Lenovo | svchost | Microsoft account auth, hits live.com catch-all |
| `data.microsoft.com` | Lenovo | svchost | settings-win.data.microsoft.com, telemetry |
| `lencr.org` | Lenovo | — | Let's Encrypt OCSP, GeoIP:US |
| `ocsp.apple.com` | Lenovo | — | Apple cert check |
| `clarity.ms` | Mac | browser | Microsoft Clarity analytics |
| `segment.io` | Mac | browser | Segment analytics (low priority) |

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `~/clash-verge-ednovas/profiles/EdNovasCloud_clash.yaml` | **Master source** — edit this |
| `~/clash-config-repo/EdNovasCloud_clash.yaml` | Git mirror of source |
| Gist `763389e1fe30b3ae79f3a75f37b4ca61` | Remote sync point; file: `EdNovasCloud_clash_new.yaml` |
| Mac `clash-verge.yaml` | Active runtime config (auto-generated, do not edit as primary) |
| Lenovo `clash-verge.yaml` | Active runtime config on Lenovo (same) |
| Lenovo `verge.yaml` | Persistent settings: `enable_external_controller: true` set here |
