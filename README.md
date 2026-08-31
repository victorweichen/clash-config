# clash-config

Clash Verge / mihomo 配置。核心是一条规矩：

> **订阅文件是上游给的，定制是我们加的，两者不要用手工混在一起。**
> 定制写在 `merge_ednovas.py` 里，每次上游更新后重新跑一遍。

机场每次重新下载订阅都是原版，手工在 4.3 万行里重打二十多处补丁必然漏。脚本
把这件事变成一条命令，并且用 `assert` 守住它依赖的上游结构——上游改了形态会**直接
报错**，而不是静默漏掉某项补丁。

---

## 文件性质：源 vs 产物

| 文件 | 性质 | 说明 |
|---|---|---|
| `merge_ednovas.py` | **源**（跟踪） | 全部定制逻辑 + 每项改动的理由和实测数据 |
| `EdNovasCloud_clash_upstream.yaml` | **源**（跟踪） | 机场原版订阅，脚本的输入 |
| `EdNovasCloud_clash_v2.yaml` | **产物**（跟踪，经 CDN 分发） | 脚本输出，Mac / Android 都订阅这份，经 CDN 分发 |
| `EdNovasCloud_clash.yaml` | 源（跟踪） | Mac 用的旧版 EdNovas 配置（已被 v2 取代，保留供参考） |
| `EdNovasCloud_clash_win.yaml` | 源（跟踪） | Lenovo 版（家庭节点直连 `100.95.126.121:1080` + `interface-name: Tailscale`） |
| `tailnet_clash_mac.yaml` / `_win.yaml` | 源（跟踪） | 纯 tailnet 配置（不含机场节点） |

`EdNovasCloud_clash_v2.yaml` / `_win.yaml` 虽是产物，但仍进 git ——因为设备是通过
CDN 订阅这份文件的，必须有个稳定 URL 可拉取。它的 diff 天然是几万行噪音（当天订阅
内容 + 补丁），真正的决策看 `merge_ednovas*.py` 的 diff，不看产物本身的 diff。

---

## 产出新配置（v2）

### 1. 下载最新订阅，覆盖仓库里的 upstream 副本

从 EdNovas 面板下载 Clash 配置，然后：

```bash
cp ~/Downloads/EdNovasCloud_clash*.yaml ~/clash-config-repo/EdNovasCloud_clash_upstream.yaml
```

原版一并纳入 git，这样 **`merge_ednovas.py` + `EdNovasCloud_clash_upstream.yaml`
可以完整复现产物**；出了问题也能 `git diff` 看出是上游改了什么、还是我们改的。
提交时把机场那边的变化（节点增删、倍率调整、策略变更）写进 commit message。

### 2. 跑合并脚本

```bash
python3 ~/clash-config-repo/merge_ednovas.py
```

正常输出类似：

```
removed dead node 0.1X 🇺🇸 美国8 from 27 groups + its definition
wrote /Users/victorchen/clash-config-repo/EdNovasCloud_clash_v2.yaml
lines 42986 -> 43061 (+75)
home+tailnet into 15 service groups, tailnet twin into 1 region refs
tsnet paired with gost in 20 groups
```

**报 `AssertionError` 说明上游变了结构**，不要绕过——去看是哪条断言，确认上游改了
什么再决定怎么调整。断言就是为了在这时候拦住你。

### 3. 校验（不要跳过）

```bash
"/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo" -t -f ~/clash-config-repo/EdNovasCloud_clash_v2.yaml
```

必须看到 `test is successful`。这一步离线校验，不影响正在运行的实例。

更严格的完整性检查（悬空引用会让配置加载失败）：

```bash
python3 - <<'EOF'
import yaml
c = yaml.safe_load(open("/Users/victorchen/clash-config-repo/EdNovasCloud_clash_v2.yaml", encoding="utf-8"))
G = {g["name"]: g for g in c["proxy-groups"]}
known = {p["name"] for p in c["proxies"]} | set(G) | {"DIRECT","REJECT","REJECT-DROP","PASS","COMPATIBLE"}
print("悬空成员:", [f"{n}->{m}" for n,g in G.items() for m in g.get("proxies",[]) if m not in known] or "none")
print("空分组:", [n for n,g in G.items() if not g.get("proxies")] or "none")
print(f"分组={len(G)} 节点={len(known)} 规则={len(c['rules'])}")
EOF
```

### 4. 推送并分发（见下方"分发到 CDN"一节）

生成后不再本地加载——commit + push + purge CDN 缓存 + curl 验证，然后各设备
（Mac / Android，将来也可以是别的手机）订阅同一个 CDN URL，点更新即可。

---

## 上游/环境漂移时要改的三个地方

都在 `merge_ednovas.py` 顶部：

| 常量 | 何时要改 | 症状 |
|---|---|---|
| `TAILNET_HOSTS` | 新增/移除 tailnet 机器 | 新机器域名解析不到 |
| `DEAD_NODES` | 机场节点复活或新节点挂掉 | 脚本报"expected group references, found none" |

**Tailscale 网卡不用手工维护**——`detect_tailnet_iface()` 每次生成时自动探测持有
100.x 地址的那个 utun。macOS 重启后编号会漂移（实际发生过 utun10 → utun5），
此时**重跑一次脚本 + 刷新 profile 即可**，不需要改代码。症状是 tailnet 经代理访问
不通，但 `ssh`/`ping` 正常（系统自身流量走 Tailscale 的更具体路由，不经 mihomo）。

查 tailnet 机器和 IP：

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale status --json | python3 -c "
import json,sys
d=json.load(sys.stdin)
for v in (d.get('Peer') or {}).values():
    ips=[i for i in (v.get('TailscaleIPs') or []) if ':' not in i]
    if ips: print(f\"{ips[0]:17s} {v['DNSName'].rstrip('.')}\")"
```

---

## 分发到 CDN（其余几个配置）

`EdNovasCloud_clash*.yaml` / `tailnet_clash_*.yaml` 经 jsDelivr 提供给两台机器订阅。
**改动 → push → purge → 必须 curl 验证**，purge 返回 `finished` 不代表边缘节点已刷新。

```bash
cd ~/clash-config-repo
git push     # 直接推即可 — TUN 开着时 git 流量走 DomainKeyword(github) 规则，
             # 自动进 EdNovas云（当前是 🏠 家庭宽带tsnet），不用手动指定代理。
             # 例外：TUN 关掉、只留系统代理时 git 不认系统代理设置，会直连
             # github 被 SNI 阻断 —— 这时才需要 -c http.proxy=socks5h://100.95.126.121:1080

F=EdNovasCloud_clash_win.yaml
curl -sS "https://purge.jsdelivr.net/gh/victorweichen/clash-config@main/$F"
curl -sS "https://cdn.jsdelivr.net/gh/victorweichen/clash-config@main/$F" | grep <改动的标记>
```

订阅地址形如：

```
https://cdn.jsdelivr.net/gh/victorweichen/clash-config@main/<文件名>
```

> 新文件名从未被缓存，立即新鲜；刚缓存不久的传播较快；老文件最顽固。

---

## 几个反复踩过的坑

- **`type: remote` 的 profile 点更新会从 URL 重新下载，覆盖本地改动。** 所以顺序永远是
  改源 → push → purge → curl 验证 → 再让设备点更新。
- **规则表首条匹配生效。** 我们的 DIRECT 覆盖之所以能压过上游的 `EdNovas云` 策略，
  靠的就是位置在前，而不是删掉上游规则。
- **`hosts` 是顶层键**，插进 `dns:` 块里会静默吞掉该块剩余内容。
- **mihomo 自己发起的 DNS 查询和出站连接走物理网卡**（绕开自己的 TUN 防环路），
  所以到 `100.x` 需要显式绑定 Tailscale 网卡——这就是 `🔗 tailnet直连` 出站存在的原因。
- **改配置前先复现、先验证根因**，不要边猜边改。长期存在的状态不可能解释新出现的故障。

---

## 相关文档

`CLAUDE.md` 记录的是更早的工作流（手工编辑源文件 + Gist 分发）和大量设备访问信息
（Lenovo/Mac mini 的 SSH、mihomo API 用法、规则排序分析等），仍有参考价值，但其中
**v2 之前的部分内容已过时**——例如它写的家庭节点是 `100.95.126.121:1080 /
interface-name: utun4`，而 Mac 现在走本地 gost 中转 `127.0.0.1:11080`。以本
README 为准。
