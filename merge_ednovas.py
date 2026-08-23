#!/usr/bin/env python3
"""Re-apply our accumulated customizations to a freshly downloaded EdNovas config.

The airport's subscription is re-downloaded periodically and always arrives
vanilla, so every local change has to be re-applied. Doing that by hand across a
43k-line file is how things silently regress, hence this script: run it after
each fresh download and the output is a complete, ready-to-load profile.

Every patch below is either (a) ours from a deliberate commit — provenance was
established by diffing against git history — or (b) required for TUN/Tailscale
correctness. Upstream's own changes are left alone, except where our DIRECT
overrides intentionally win by sitting earlier in `rules` (first match wins).

The generated profile is NOT tracked in git: it is a build artifact of this
script plus whatever the subscription happened to contain that day.

Usage:  python3 merge_ednovas.py            # SRC -> DST
Verify: verge-mihomo -t -f <DST>            # never load an unvalidated config
"""
import re

SRC = "/Users/victorchen/Downloads/EdNovasCloud_clash .yaml"
DST = "/Users/victorchen/clash-config-repo/EdNovasCloud_clash_v2.yaml"

HOME   = "'🏠 家庭宽带美国'"      # gost relay -> Mac mini SOCKS5
TSNET  = "'🏠 家庭宽带tsnet'"     # mihomo's in-process tailscale node
TDIRECT = "'🔗 tailnet直连'"      # DIRECT pinned to the Tailscale interface
US     = "'🇺🇲 美国节点'"
UST    = "'🇺🇲 美国节点+tailnet'"
GEMT   = "'🇺🇲 Gemini+tailnet'"

# Tailnet machines pinned statically: `hosts` is consulted before any resolver,
# so these keep resolving even when the utun number drifts and the interface-
# bound nameserver-policy below goes deaf. Tailscale IPs are stable per device.
# Refresh with: tailscale status --json
TAILNET_HOSTS = {
    "vicfels-mac-mini.tail2453b3.ts.net":      "100.95.126.121",
    "victor-lenovo.tail2453b3.ts.net":         "100.103.10.73",
    "mihomo-mbp.tail2453b3.ts.net":            "100.114.158.113",
    "huawei-x5.tail2453b3.ts.net":             "100.92.199.95",
    "xiaofangs-macbook-pro.tail2453b3.ts.net": "100.126.22.3",
}

# macOS renumbers utun interfaces across reboots (utun5->utun4 has bitten us).
# When tailnet access breaks, check `ifconfig` for the interface holding a 100.x
# address and update this, then re-run.
TAILNET_IFACE = "utun10"

# Measured dead 2026-08-17: server TCP connects but the vmess tunnel carries
# nothing — 4/4 requests timed out at a flat 5s (its server is japan.ysqhq.top
# despite the 美国8 label). Delete from this list if the airport revives it.
DEAD_NODES = ["0.1X 🇺🇸 美国8"]

# Health-check cadence for auto-selecting groups. Upstream ships 自动选择 with
# interval 86400, i.e. a dead node is not noticed for a day — the exact failure
# mode that kept stranding us on nodes that had stopped working.
AUTOSELECT_INTERVAL = 300

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
    """Insert `member` at the head of a group's proxies list."""
    i = group_idx(name)
    assert "proxies: [" in lines[i], f"group {name} has no proxies list"
    assert member not in lines[i], f"{member} already in group {name}"
    lines[i] = lines[i].replace("proxies: [", f"proxies: [{member}, ", 1)


def inject_after(anchor, insert, expect_min, what):
    """Insert `insert` right after `anchor` inside every group's proxies list.
    Only the part after 'proxies: [' is examined, so a group's own name never
    matches (`name: EdNovas云,` must not count as a member reference)."""
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


# ── 1. top-level ipv6: false ─────────────────────────────────────────
# mihomo's TUN claims the whole IPv6 space but does not forward it, so every
# DIRECT-routed IPv6 destination returns "no route to host". Must be top level;
# patching the runtime API or clash-verge.yaml is undone on the next Apply.
assert not lines[0].startswith("ipv6:"), "ipv6 already at top?"
lines.insert(0, "ipv6: false")

# ── 2. DNS ───────────────────────────────────────────────────────────
# Upstream mixes 8.8.8.8/1.1.1.1 into `nameserver`, so mihomo races them and a
# foreign resolver can win for domestic sites — baidu/iqiyi then land on distant
# CDN edges, and CN-misclassified IPs get routed out through US proxies.
# Domestic-first in nameserver; foreign resolvers only in fallback.
i = find(lambda l: l.strip().startswith("nameserver: [223.5.5.5"), "dns nameserver")[0]
lines[i:i + 1] = [
    "    nameserver: [223.5.5.5, 223.6.6.6, 119.29.29.29, 'https://doh.pub/dns-query', 'https://dns.alidns.com/dns-query']",
    # MagicDNS. A plain `100.100.100.100` entry does NOT work: mihomo sends its
    # own DNS queries from the physical interface (bypassing its own TUN to
    # avoid a loop), and Tailscale's resolver is only reachable over the
    # Tailscale interface — measured as
    # `read udp 192.168.1.47:...->100.100.100.100:53: i/o timeout`.
    # Binding the query to that interface fixes it; TAILNET_HOSTS covers the
    # machines we actually use when the interface name drifts.
    "    nameserver-policy:",
    f"        '+.ts.net': ['100.100.100.100#{TAILNET_IFACE}']",
    "    fallback: ['https://1.1.1.1/dns-query', 'https://8.8.8.8/dns-query', 'tls://1.1.1.1', 'tls://8.8.8.8']",
    "    fallback-filter:",
    "        geoip: true",
    "        geoip-code: CN",
    "        ipcidr: ['240.0.0.0/4', '0.0.0.0/8']",
]

# fake-ip would hand out a 198.18.x.x for tailnet names, so the connection gets
# routed by domain (-> MATCH -> proxy) instead of straight down the tailnet.
# Filtering *.ts.net makes mihomo return the real 100.x address.
i = find(lambda l: l.strip().startswith("fake-ip-filter: ["), "fake-ip-filter")[0]
assert "ts.net" not in lines[i], "ts.net already filtered"
lines[i] = lines[i].replace("fake-ip-filter: [", "fake-ip-filter: ['+.ts.net', ", 1)

# `hosts` is a TOP-LEVEL key — inserting it inside the dns: block silently
# swallows the rest of that block, so anchor on `dns:` and go above it.
i = find(lambda l: l == "dns:", "top-level dns:")[0]
lines[i:i] = ["hosts:"] + [f"    '{h}': {ip}" for h, ip in TAILNET_HOSTS.items()]

# ── 3. our three outbounds ───────────────────────────────────────────
pg = find(lambda l: l.startswith("proxy-groups:"), "proxy-groups:")[0]

# (a) home broadband over the local gost relay. udp: true matters — every other
# node has it, and without it mihomo never attempts UDP ASSOCIATE here.
lines.insert(pg, f"    - {{ name: {HOME}, type: socks5, server: 127.0.0.1, port: 11080, udp: true }}")

# (b) native tailscale outbound. mihomo joins the tailnet in-process, so this
# needs no system Tailscale client, no utun, and never touches system DNS.
# auth-key is omitted on purpose: mihomo then logs an interactive login URL, so
# no credential lives in this file. state-dir must be RELATIVE (absolute paths
# are rejected by SAFE_PATHS) and holds the node identity — losing it means
# re-authorizing.
lines.insert(pg + 1,
             f"    - {{ name: {TSNET}, type: tailscale, hostname: mihomo-mbp, "
             f"state-dir: ./ts-state-mihomo, exit-node: 100.95.126.121, "
             f"exit-node-allow-lan-access: false, ephemeral: false, udp: true }}")

# (c) DIRECT pinned to the Tailscale interface. Plain DIRECT cannot reach
# tailnet addresses: with auto-detect-interface, mihomo binds its outbound
# socket to the physical NIC, and 100.x only routes over the Tailscale
# interface — measured as `dial tcp 100.95.126.121:9443: i/o timeout` while the
# host's own stack reached the same address in 0.77s. (Tailscale's
# 100.64.0.0/10 route is more specific than the TUN default route, so host
# traffic never enters mihomo; only apps using the system proxy hit this.)
lines.insert(pg + 2, f"    - {{ name: {TDIRECT}, type: direct, interface-name: {TAILNET_IFACE} }}")

# ── 4. proxy-groups ──────────────────────────────────────────────────
prepend_member("EdNovas云", HOME)
prepend_member("'🇺🇲 美国节点'", HOME)

# The home exits are free (they do not consume the airport's metered quota) and
# measured faster than the airport's US nodes, so let the auto-selector pick
# them first.
prepend_member("自动选择", HOME)

# Upstream downgraded 🇺🇲 美国节点 from url-test to a plain select, which kills
# auto-failover — EdNovas US nodes drop often and a select just sits on a dead
# one. Restore url-test so it picks whichever candidate is actually healthy.
i = group_idx("'🇺🇲 美国节点'")
assert ", type: select," in lines[i], "美国节点 is no longer a select — recheck upstream"
lines[i] = lines[i].replace(", type: select,", ", type: url-test,", 1)
assert lines[i].rstrip().endswith("] }"), "unexpected group line tail"
lines[i] = lines[i].rstrip()[:-len("] }")] + "], url: 'http://1.1.1.1/', interval: 300 }"

# Gemini reaches for the tailnet exit first (a US residential IP is treated far
# better than a datacenter one).
prepend_member("Gemini", GEMT)

# Tighten the auto-selector's health check (see AUTOSELECT_INTERVAL).
i = group_idx("自动选择")
assert "interval: 86400" in lines[i], "自动选择 interval changed upstream — recheck"
lines[i] = lines[i].replace("interval: 86400", f"interval: {AUTOSELECT_INTERVAL}", 1)

# Upstream restructured: service groups now list raw nodes and reference
# EdNovas云 instead of the region groups. Give each of them direct access to the
# home exit and to the url-test tailnet group.
n_svc = inject_after("EdNovas云,", f"{HOME}, {UST},", 14, "service groups")
# Wherever the region group is offered as a member, offer its tailnet twin too.
n_tail = inject_after(US + ",", UST + ",", 1, "region-group refs")

# Derive the tailnet US group from upstream's *current* US node list so it can
# never reference a node this subscription dropped.
us_i = group_idx("'🇺🇲 美国节点'")
us_nodes = lines[us_i].split("proxies: [", 1)[1].rsplit("]", 1)[0]
us_nodes = us_nodes.replace(HOME + ", ", "").replace(UST + ", ", "")
assert "美国" in us_nodes, "could not parse US node list"

new_groups = [
    f"    - {{ name: '🇺🇲 美国节点+tailnet', type: url-test, proxies: [{HOME}, {us_nodes}], url: 'http://1.1.1.1/', interval: 300 }}",
    # Gemini candidates measured 2026-08-17 by binding one HTTP listener per
    # node and checking which ones Google keeps on google.com: 美国2 and 美国17
    # get geo-redirected to google.com.hk (Google reads their US IPs as HK/CN,
    # which is what makes Gemini report the wrong location), and 美国8 is dead.
    # Ordered by measured latency to gemini.google.com; the health check hits
    # Gemini itself so a node Google starts down-ranking drops out on its own.
    f"    - {{ name: '🇺🇲 Gemini+tailnet', type: url-test, proxies: ['0.2X 🇺🇸 美国3', '0.1X 🇺🇸 美国23', '0.8X 🇺🇸 美国16', '0.8X 🇺🇸 美国4', '1.0X 🇺🇸 美国9', '0.5X 🇺🇸 美国10', {HOME}], url: 'https://gemini.google.com/app', expected-status: '200', interval: 300 }}",
    # 中国以外 and 🇺🇲 美国Gemini were dropped by upstream — referencing them
    # would fail config load, so OpenRouter's list is rebuilt without them.
    f"    - {{ name: OpenRouter, type: select, proxies: [自动选择, {US}, {UST}, {GEMT}] }}",
]
lines[us_i + 1:us_i + 1] = new_groups

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
        for pat in (q + ", ", ", " + q, q):   # wherever it sits in the sequence
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

# ── 6. pair tsnet with the gost node everywhere ──────────────────────
# Verified working end-to-end 2026-08-18 (egress 76.132.13.63 Comcast US, the
# same home broadband the gost path exits from), so it sits directly after the
# socks5 node in every group that offers it — url-test groups included, where
# the two home paths compete on measured latency. Runs AFTER 美国节点+tailnet is
# derived, so tsnet never leaks into that derived node list.
# Caveat: tsnet initialises lazily, so the first request after mihomo starts can
# time out and a url-test health check may briefly mark it dead.
n_ts = inject_after(HOME + ",", TSNET + ",", 15, "tsnet alongside gost")
for i, l in enumerate(lines):          # groups where the gost node sits last
    if not l.lstrip().startswith("- { name: "):
        continue
    head, sep, body = l.partition("proxies: [")
    if not sep or TSNET in body or HOME + "]" not in body:
        continue
    lines[i] = head + sep + body.replace(HOME + "]", f"{HOME}, {TSNET}]", 1)
    n_ts += 1

# ── 7. rule-provider: full Telegram ASN ranges ───────────────────────
i = find(lambda l: l.strip().startswith("china-ip: {"), "china-ip rule-provider")[0]
lines.insert(i + 1, "    telegram-ip: { type: http, behavior: ipcidr, url: 'https://cdn.jsdelivr.net/gh/Loyalsoldier/clash-rules@release/telegramcidr.txt', path: ./ruleset/telegram-ip.yaml, interval: 86400 }")

# ── 8. rules ─────────────────────────────────────────────────────────
# These sit at the top of `rules`, so they win over upstream's own entries for
# the same domains (first match wins) — that is how the Microsoft/Akamai block
# below overrides upstream's newer "send it through EdNovas云" policy.
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
    "    # ── gate.com: site migrated off gate.io; new domain had no rule ──",
    "    - 'DOMAIN-SUFFIX,gate.com,EdNovas云'",
    "    - 'DOMAIN-SUFFIX,openrouter.ai,OpenRouter'",
    "    # ── Microsoft/OneDrive/Akamai direct to save quota (upstream now ──",
    "    # ── sends these via EdNovas云; these earlier rules override that). ──",
] + [f"    - 'DOMAIN-KEYWORD,{d},DIRECT'" for d in MS_DIRECT_KEYWORDS] \
  + [f"    - 'DOMAIN-SUFFIX,{d},DIRECT'" for d in MS_DIRECT_SUFFIXES]

ri = find(lambda l: l == "rules:", "rules:")[0]
lines[ri + 1:ri + 1] = head_rules

# US traffic prefers the US group (which includes the home exits) over the
# MATCH catch-all. US is already quoted, so don't nest quotes here.
gi = find(lambda l: "GEOIP,CN," in l, "GEOIP,CN tail rule")[0]
lines.insert(gi, "    - 'GEOIP,US,🇺🇲 美国节点'")

open(DST, "w", encoding="utf-8").write("\n".join(lines))
print(f"wrote {DST}")
print(f"lines {n_before} -> {len(lines)} (+{len(lines) - n_before})")
print(f"home+tailnet into {n_svc} service groups, tailnet twin into {n_tail} region refs")
print(f"tsnet paired with gost in {n_ts} groups")
