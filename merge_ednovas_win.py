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

Windows DOES use an interface-pinned DIRECT outbound for tailnet traffic
(🔗 tailnet直连, interface-name: Tailscale) — unlike Mac this needs no drift
detection, since "Tailscale" is a stable Windows adapter name, so it's just a
literal instead of TAILNET_IFACE auto-detection. Confirmed 2026-08-31 this is
actually necessary here too, not just a Mac quirk: mihomo's plain DIRECT
returned 504 Gateway Timeout dialing a tailnet address that Test-NetConnection
(raw OS TCP, bypassing mihomo) reached fine — same auto-detect-interface bug,
platform-independent.

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
TDIRECT = "'🔗 tailnet直连'"    # DIRECT pinned to the Tailscale interface
UST  = "'🇺🇲 美国节点+tailnet'"
GEMT = "'🇺🇲 Gemini+tailnet'"

# Same airport, same node identity — see merge_ednovas.py for the measurement.
# 2026-09-04: EdNovas's protocol upgrade renamed the whole roster (vmess "X"
# -> vless "X VLESS"); 美国8 is still dead under its new name too.
DEAD_NODES = ["0.1X 🇺🇸 美国8 VLESS"]

# The old "VLESS 中转" line no longer exists post-upgrade (see
# merge_ednovas.py) — nothing to filter right now. Left in place in case
# EdNovas ships another broken batch under a new suffix.
DEAD_NAME_SUFFIXES = []

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

# MagicDNS resolution. Unlike on macOS this needs no interface-drift
# handling — "Tailscale" is a stable adapter name on Windows.
ts_policy_entry = f"'+.ts.net': ['100.100.100.100#{TAILNET_IFACE}']"

# Upstream sometimes ships its own `nameserver-policy` (added for ednovas.*
# domains in a later subscription refresh) sitting just above `nameserver:`.
# YAML forbids two `nameserver-policy` keys in the same mapping, so if one is
# already there, merge our entry into it instead of inserting a second one.
existing_policy_i = None
for j in range(max(0, i - 5), i):
    if lines[j].strip().startswith("nameserver-policy:") and lines[j].rstrip().endswith("}"):
        existing_policy_i = j
        break

if existing_policy_i is not None:
    assert ts_policy_entry.split(":", 1)[0] not in lines[existing_policy_i], "+.ts.net already in upstream nameserver-policy"
    head = lines[existing_policy_i].rstrip()
    assert head.endswith("}"), "upstream nameserver-policy not flow-style, adjust merge"
    lines[existing_policy_i] = head[:-1].rstrip().rstrip(",") + f", {ts_policy_entry} }}"
    lines[i:i + 1] = [
        "    nameserver: [223.5.5.5, 223.6.6.6, 119.29.29.29, 'https://doh.pub/dns-query', 'https://dns.alidns.com/dns-query']",
        "    fallback: ['https://1.1.1.1/dns-query', 'https://8.8.8.8/dns-query', 'tls://1.1.1.1', 'tls://8.8.8.8']",
        "    fallback-filter:",
        "        geoip: true",
        "        geoip-code: CN",
        "        ipcidr: ['240.0.0.0/4', '0.0.0.0/8']",
    ]
else:
    lines[i:i + 1] = [
        "    nameserver: [223.5.5.5, 223.6.6.6, 119.29.29.29, 'https://doh.pub/dns-query', 'https://dns.alidns.com/dns-query']",
        "    nameserver-policy:",
        f"        {ts_policy_entry}",
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

# ── 3b. DIRECT pinned to the Tailscale interface, for tailnet traffic ─
# Plain DIRECT cannot reach tailnet addresses: mihomo's auto-detect-interface
# binds the outbound socket to the physical NIC, and 100.x only routes over
# the Tailscale interface. Confirmed 2026-08-31 via mihomo's per-proxy
# delay-check (bypasses the rule table): DIRECT to a real, definitely-up
# tailnet target returned 504 Gateway Timeout, while Test-NetConnection to the
# exact same address (raw OS TCP, no mihomo) succeeded — same root cause as
# the bug fixed on Mac, just without the utun-renumbering complication, since
# "Tailscale" is a stable Windows adapter name (unlike this node's `interface-
# name` above, this doesn't need drift detection — see module docstring for
# why Mac needed tsnet instead of just doing this).
lines.insert(pg + 1, f"    - {{ name: {TDIRECT}, type: direct, interface-name: {TAILNET_IFACE} }}")

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
# the home exit too.
n_svc = inject_after("EdNovas云,", f"{HOME},", 14, "service groups")

# Named to match the Mac config (🇺🇲 美国节点+tailnet / 🇺🇲 Gemini+tailnet) even
# though there's no tsnet node to pair with here — "+tailnet" on this platform
# just means "includes the SOCKS5 home broadband node", which both do.
#
# Derive a Gemini-safe US group. Candidates measured on the Mac 2026-08-17 by
# binding one HTTP listener per node and checking which ones Google keeps on
# google.com — 美国2/美国17 get geo-redirected to google.com.hk (Google reads
# their US IPs as HK/CN), and 美国8 is dead. Same airport serves both
# platforms, so the same exclusions apply here.
us_i = group_idx("'🇺🇲 美国节点'")

# 🇺🇲 美国节点+tailnet: same node list as 🇺🇲 美国节点 (which already got HOME
# prepended above), just under the Mac-matching name.
us_nodes = lines[us_i].split("proxies: [", 1)[1].rsplit("]", 1)[0]
assert HOME in us_nodes, "🇺🇲 美国节点 should already have the home node prepended"
assert "美国" in us_nodes, "could not parse US node list"

new_groups = [
    f"    - {{ name: {UST}, type: url-test, proxies: [{us_nodes}], url: 'http://1.1.1.1/', interval: 300 }}",
    f"    - {{ name: {GEMT}, type: url-test, proxies: [{HOME}, '0.2X 🇺🇸 美国3 VLESS', '0.1X 🇺🇸 美国23 VLESS', '0.8X 🇺🇸 美国16 VLESS', '0.8X 🇺🇸 美国4 VLESS', '1.0X 🇺🇸 美国9 VLESS', '0.5X 🇺🇸 美国10 VLESS'], url: 'https://gemini.google.com/app', expected-status: '200', interval: 300 }}",
    # 中国以外 and 🇺🇲 美国Gemini were dropped by upstream — OpenRouter's list is
    # rebuilt without them (referencing a nonexistent group fails config load).
    f"    - {{ name: OpenRouter, type: select, proxies: [自动选择, {US}, {UST}, {GEMT}] }}",
]
lines[us_i + 1:us_i + 1] = new_groups
prepend_member("Gemini", GEMT)
# Claude gets both tailnet variants directly (not part of the blanket
# service-group injection above, which only adds the plain home node).
prepend_member("Claude", UST)
prepend_member("Claude", GEMT)

# ── 5. drop nodes measured dead ──────────────────────────────────────
name_pat = re.compile(r"- \{ name: '([^']*)', type: (?:vmess|vless),")
suffix_matches = sorted({
    m.group(1) for l in lines if (m := name_pat.search(l))
    if any(m.group(1).endswith(suf) for suf in DEAD_NAME_SUFFIXES)
})
if DEAD_NAME_SUFFIXES:
    assert suffix_matches, f"{DEAD_NAME_SUFFIXES}: expected matching nodes, found none"

for dead in DEAD_NODES + suffix_matches:
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
          if l.lstrip().startswith("- { name: " + q + ",") and re.search(r"type: (vmess|vless)", l)]
    assert len(di) == 1, f"{dead}: expected 1 node definition, found {len(di)}"
    del lines[di[0]]
    still = [i for i, l in enumerate(lines) if q in l]
    assert not still, f"{dead}: still referenced at lines {still}"
    print(f"removed dead node {dead} from {n_ref} groups + its definition")

# ── 5b. keep high-multiplier nodes out of 自动选择's candidate pool ────
# See merge_ednovas.py for the rationale — url-test races on latency only,
# with no notion of quota cost, so reuse upstream's own "高倍率节点" roster
# instead of hardcoding a multiplier cutoff.
PSEUDO_NAMES = ("剩余流量：", "距离下次重置剩余：", "套餐到期：")
hi_i = group_idx("高倍率节点")
hi_body = lines[hi_i].partition("proxies: [")[2].rsplit("]", 1)[0]
hi_members = [m.strip().strip("'\"") for m in hi_body.split(", ")]
hi_members = [m for m in hi_members if not m.startswith(PSEUDO_NAMES)]
assert hi_members, "高倍率节点: expected real member nodes, found none"

as_i = group_idx("自动选择")
head, sep, body = lines[as_i].partition("proxies: [")
rest, _, tail = body.rpartition("]")
n_removed = 0
for m in hi_members:
    q = f"'{m}'"
    for pat in (q + ", ", ", " + q, q):
        if pat in rest:
            rest = rest.replace(pat, "", 1)
            n_removed += 1
            break
assert n_removed == len(hi_members), f"高倍率节点: expected to remove {len(hi_members)} from 自动选择, removed {n_removed}"
lines[as_i] = head + sep + rest + "]" + tail
print(f"removed {n_removed} high-multiplier nodes from 自动选择")

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
td = TDIRECT.strip("'")
head_rules = [
    "    # ── Tailscale CGNAT: must be first, else TUN loops on the SOCKS5 relay ──",
    f"    - 'IP-CIDR,100.64.0.0/10,{td},no-resolve'",
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
    "    # ── tailnet: must use the interface-pinned outbound, not DIRECT ──",
    f"    - 'DOMAIN-SUFFIX,ts.net,{td}'",
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
