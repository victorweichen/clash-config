#!/usr/bin/env python3
"""Re-apply our cross-platform customizations to a fresh EdNovas subscription,
producing the Windows (Lenovo) profile.

Sibling of merge_ednovas.py — same upstream input, same subscription, but this
one is deliberately narrower: only the patches that are platform-agnostic or
that have a direct Windows equivalent. Explicitly OUT of scope here (Mac-only,
see merge_ednovas.py for why each exists):
  - the local gost relay node (127.0.0.1:11080) — Windows connects to the Mac
    mini's SOCKS5 directly instead (100.95.126.121:1080), which is already
    what this file's home node does
  - the mihomo-native tsnet node — tied to a specific tsnet auth/identity on
    the Mac; a Windows tsnet node would need its own
  - TAILNET_IFACE auto-detection and the interface-pinned DIRECT outbound —
    Windows' Tailscale interface has a stable name ("Tailscale", no utun-style
    drift) so the mechanism that motivated it doesn't apply the same way, and
    whether Windows' plain DIRECT can actually reach 100.x through mihomo's
    TUN is UNVERIFIED. If tailnet sites are unreachable from a browser on
    Lenovo the way they were on Mac before that fix, the same interface-pinned
    DIRECT outbound (with interface-name: Tailscale instead of a detected
    utun) is the next thing to try.

Unlike merge_ednovas.py's output (a Local-only test profile, deliberately kept
out of git), THIS script's output is the actual file Lenovo subscribes to via
jsDelivr — it stays tracked, and deploying it means committing + pushing +
purging the CDN cache. See README.md.

Usage:  python3 merge_ednovas_win.py
Verify: verge-mihomo -t -f <DST>            # never load an unvalidated config
"""
import re

REPO = "/Users/victorchen/clash-config-repo"
SRC = f"{REPO}/EdNovasCloud_clash_upstream.yaml"   # shared with the Mac build
DST = f"{REPO}/EdNovasCloud_clash_win.yaml"

HOME = "'🏠 家庭宽带美国'"      # direct SOCKS5 to the Mac mini, no local relay
US   = "'🇺🇲 美国节点'"

# Same airport, same node identity — see merge_ednovas.py for the measurement.
DEAD_NODES = ["0.1X 🇺🇸 美国8"]

AUTOSELECT_INTERVAL = 300   # upstream ships 86400 (24h) — see merge_ednovas.py

# Tailnet machines pinned statically for MagicDNS-name resolution (see the DNS
# section below). Keep in sync with merge_ednovas.py's TAILNET_HOSTS.
TAILNET_HOSTS = {
    "vicfels-mac-mini.tail2453b3.ts.net":      "100.95.126.121",
    "victor-lenovo.tail2453b3.ts.net":         "100.103.10.73",
    "mihomo-mbp.tail2453b3.ts.net":            "100.114.158.113",
    "huawei-x5.tail2453b3.ts.net":             "100.92.199.95",
    "xiaofangs-macbook-pro.tail2453b3.ts.net": "100.126.22.3",
}
# Windows' Tailscale adapter keeps a stable friendly name — no drift-detection
# needed the way macOS utun numbers require.
TAILNET_IFACE = "Tailscale"

text = open(SRC, encoding="utf-8").read()
lines = text.split("\n")
n_before = len(lines)


def find(pred, what):
    hits = [i for i, l in enumerate(lines) if pred(l)]
    assert hits, f"NOT FOUND: {what}"
    return hits


def group_idx(name):
    pat = re.compile(r"^\s*- \{ name: " + re.escape(name) + r",")
    return find(lambda l: pat.match(l), f"group {name}")[0]


def prepend_member(name, member):
    i = group_idx(name)
    assert "proxies: [" in lines[i], f"group {name} has no proxies list"
    assert member not in lines[i], f"{member} already in group {name}"
    lines[i] = lines[i].replace("proxies: [", f"proxies: [{member}, ", 1)


def inject_after(anchor, insert, expect_min, what):
    n = 0
    for i, l in enumerate(lines):
        if not l.lstrip().startswith("- { name: "):
            continue
        head, sep, body = l.partition("proxies: [")
        if not sep or anchor not in body or insert.split(",")[0] in body:
            continue
        lines[i] = head + sep + body.replace(anchor, anchor + " " + insert, 1)
        n += 1
    assert n >= expect_min, f"{what}: expected >={expect_min} groups, got {n}"
    return n


# ── 1. ipv6: false (same mihomo TUN/IPv6 gateway bug as Mac) ─────────
assert not lines[0].startswith("ipv6:"), "ipv6 already at top?"
lines.insert(0, "ipv6: false")

# ── 2. DNS ───────────────────────────────────────────────────────────
i = find(lambda l: l.strip().startswith("nameserver: [223.5.5.5"), "dns nameserver")[0]
lines[i:i + 1] = [
    "    nameserver: [223.5.5.5, 223.6.6.6, 119.29.29.29, 'https://doh.pub/dns-query', 'https://dns.alidns.com/dns-query']",
    # MagicDNS resolution. Unlike on macOS this needs no interface-drift
    # handling — "Tailscale" is a stable adapter name on Windows.
    "    nameserver-policy:",
    f"        '+.ts.net': ['100.100.100.100#{TAILNET_IFACE}']",
    "    fallback: ['https://1.1.1.1/dns-query', 'https://8.8.8.8/dns-query', 'tls://1.1.1.1', 'tls://8.8.8.8']",
    "    fallback-filter:",
    "        geoip: true",
    "        geoip-code: CN",
    "        ipcidr: ['240.0.0.0/4', '0.0.0.0/8']",
]

i = find(lambda l: l.strip().startswith("fake-ip-filter: ["), "fake-ip-filter")[0]
assert "ts.net" not in lines[i], "ts.net already filtered"
lines[i] = lines[i].replace("fake-ip-filter: [", "fake-ip-filter: ['+.ts.net', ", 1)

i = find(lambda l: l == "dns:", "top-level dns:")[0]
lines[i:i] = ["hosts:"] + [f"    '{h}': {ip}" for h, ip in TAILNET_HOSTS.items()]

# ── 3. home node — Windows connects directly, no local relay ─────────
pg = find(lambda l: l.startswith("proxy-groups:"), "proxy-groups:")[0]
lines.insert(pg,
    f"    - {{ name: {HOME}, type: socks5, server: 100.95.126.121, port: 1080, "
    f"interface-name: {TAILNET_IFACE}, udp: true }}")

# ── 4. proxy-groups ──────────────────────────────────────────────────
prepend_member("EdNovas云", HOME)
prepend_member("'🇺🇲 美国节点'", HOME)
prepend_member("自动选择", HOME)

i = group_idx("'🇺🇲 美国节点'")
assert ", type: select," in lines[i], "美国节点 is no longer a select — recheck upstream"
lines[i] = lines[i].replace(", type: select,", ", type: url-test,", 1)
assert lines[i].rstrip().endswith("] }"), "unexpected group line tail"
lines[i] = lines[i].rstrip()[:-len("] }")] + "], url: 'http://1.1.1.1/', interval: 300 }"

i = group_idx("自动选择")
assert "interval: 86400" in lines[i], "自动选择 interval changed upstream — recheck"
lines[i] = lines[i].replace("interval: 86400", f"interval: {AUTOSELECT_INTERVAL}", 1)

# Upstream restructured: service groups reference EdNovas云 directly. Give them
# the home exit too (no tailnet-url-test twin on Windows — see module docstring).
n_svc = inject_after("EdNovas云,", f"{HOME},", 14, "service groups")

# Derive a Gemini-safe US group. Candidates measured on the Mac 2026-08-17 by
# binding one HTTP listener per node and checking which ones Google keeps on
# google.com — 美国2/美国17 get geo-redirected to google.com.hk (Google reads
# their US IPs as HK/CN), and 美国8 is dead. Same airport serves both
# platforms, so the same exclusions apply here.
us_i = group_idx("'🇺🇲 美国节点'")
new_groups = [
    "    - { name: '🇺🇲 Gemini', type: url-test, proxies: ['0.2X 🇺🇸 美国3', '0.1X 🇺🇸 美国23', '0.8X 🇺🇸 美国16', '0.8X 🇺🇸 美国4', '1.0X 🇺🇸 美国9', '0.5X 🇺🇸 美国10'], url: 'https://gemini.google.com/app', expected-status: '200', interval: 300 }",
    # 中国以外 and 🇺🇲 美国Gemini were dropped by upstream — OpenRouter's list is
    # rebuilt without them (referencing a nonexistent group fails config load).
    f"    - {{ name: OpenRouter, type: select, proxies: [自动选择, {US}, '🇺🇲 Gemini'] }}",
]
lines[us_i + 1:us_i + 1] = new_groups
prepend_member("Gemini", "'🇺🇲 Gemini'")

# ── 5. drop nodes measured dead ──────────────────────────────────────
for dead in DEAD_NODES:
    q = f"'{dead}'"
    n_ref = 0
    for i, l in enumerate(lines):
        if not l.lstrip().startswith("- { name: "):
            continue
        head, sep, body = l.partition("proxies: [")
        if not sep or q not in body:
            continue
        for pat in (q + ", ", ", " + q, q):
            if pat in body:
                body = body.replace(pat, "", 1)
                break
        lines[i] = head + sep + body
        n_ref += 1
    assert n_ref, f"{dead}: expected group references, found none"
    di = [i for i, l in enumerate(lines)
          if l.lstrip().startswith("- { name: " + q + ",") and "type: vmess" in l]
    assert len(di) == 1, f"{dead}: expected 1 node definition, found {len(di)}"
    del lines[di[0]]
    still = [i for i, l in enumerate(lines) if q in l]
    assert not still, f"{dead}: still referenced at lines {still}"
    print(f"removed dead node {dead} from {n_ref} groups + its definition")

# ── 6. rule-provider: full Telegram ASN ranges ───────────────────────
i = find(lambda l: l.strip().startswith("china-ip: {"), "china-ip rule-provider")[0]
lines.insert(i + 1, "    telegram-ip: { type: http, behavior: ipcidr, url: 'https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/telegramcidr.txt', path: ./ruleset/telegram-ip.yaml, interval: 86400 }")

# ── 7. rules ─────────────────────────────────────────────────────────
MS_DIRECT_KEYWORDS = ["1drv", "onedrive", "skydrive"]
MS_DIRECT_SUFFIXES = [
    "livefilestore.com", "oneclient.sfx.ms", "onedrive.com", "onedrive.live.com",
    "photos.live.com", "skydrive.wns.windows.com", "spoprod-a.akamaihd.net",
    "storage.live.com", "storage.msn.com", "microsoftpersonalcontent.com",
    "activity.windows.com", "config.office.com", "events.data.microsoft.com",
    "ecs.office.com", "wns.windows.com", "sharepoint.com", "windowsupdate.com",
    "update.microsoft.com", "delivery.mp.microsoft.com",
    "dl.delivery.mp.microsoft.com", "download.windowsupdate.com",
    "akamai.net", "akamaized.net", "akamaihd.net", "akamaiedge.net",
    "akamaistream.net", "sadownload.mcafee.com", "datadoghq.com", "slackb.com",
]
head_rules = [
    "    # ── Tailscale CGNAT: must be first, else TUN loops on the SOCKS5 relay ──",
    "    - 'IP-CIDR,100.64.0.0/10,DIRECT,no-resolve'",
    "    # ── Telegram: desktop client dials cached DC IPs directly, so the ──",
    "    # ── domain rules below aren't enough; needs the full ASN ranges. ──",
    "    - 'RULE-SET,telegram-ip,EdNovas云'",
    "    - 'DOMAIN-KEYWORD,telegram,EdNovas云'",
    "    # ── config-update channel: must stay DIRECT or we can't self-heal ──",
    "    - 'DOMAIN-SUFFIX,jsdelivr.net,DIRECT'",
    "    - 'DOMAIN-SUFFIX,fastly.net,DIRECT'",
    "    - 'DOMAIN-SUFFIX,fastlylb.net,DIRECT'",
    "    - 'DOMAIN,cdn.nmsl.sb,DIRECT'",
    "    # ── Tailscale control plane / DERP: never through the proxy ──",
    "    - 'DOMAIN-SUFFIX,tailscale.com,DIRECT'",
    "    - 'DOMAIN-SUFFIX,tailscale.io,DIRECT'",
    "    - 'DOMAIN-SUFFIX,tailscale.net,DIRECT'",
    "    # ── MagicDNS names resolve to 100.x, which the CGNAT rule already ──",
    "    # ── sends DIRECT. UNVERIFIED on Windows whether mihomo's DIRECT ──",
    "    # ── outbound actually reaches the tailnet through TUN the way it ──",
    "    # ── silently failed to on macOS — see module docstring. ──",
    "    - 'DOMAIN-SUFFIX,ts.net,DIRECT'",
    "    - 'DOMAIN-SUFFIX,gate.com,EdNovas云'",
    "    - 'DOMAIN-SUFFIX,openrouter.ai,OpenRouter'",
    "    # ── Microsoft/OneDrive/Akamai direct to save quota (upstream now ──",
    "    # ── sends these via EdNovas云; these earlier rules override that). ──",
] + [f"    - 'DOMAIN-KEYWORD,{d},DIRECT'" for d in MS_DIRECT_KEYWORDS] \
  + [f"    - 'DOMAIN-SUFFIX,{d},DIRECT'" for d in MS_DIRECT_SUFFIXES]

ri = find(lambda l: l == "rules:", "rules:")[0]
lines[ri + 1:ri + 1] = head_rules

gi = find(lambda l: "GEOIP,CN," in l, "GEOIP,CN tail rule")[0]
lines.insert(gi, "    - 'GEOIP,US,🇺🇲 美国节点'")

open(DST, "w", encoding="utf-8").write("\n".join(lines))
print(f"wrote {DST}")
print(f"lines {n_before} -> {len(lines)} (+{len(lines) - n_before})")
print(f"home node into {n_svc} service groups")
