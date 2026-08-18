# 🌐 IP 变动监控与 Bark 实时推送

基于 **Python 3.13** 和 **uv** 的公网 IP 变动监控工具；现在会同时检测：

- **国内公网 IP**：通过国内检测源获取，适合查看家庭/校园/运营商真实出口。
- **国外出口 IP**：通过海外检测源获取，通常对应代理节点出口。

检测到任一 IP 变化后，通过 Bark 推送到 iPhone/iPad。

## ✨ 特性

- **国内 / 国外双通道**：两个 IP 独立检测、独立缓存、独立判断变化。
- **多源容灾**：每个通道都有多个公网 IP 探测源自动切换。
- **指数退避重试**：单个探测源失败后不会立即高频重试。
- **单通道容错**：国内或国外其中一组接口失败，不影响另一组继续监控。
- **连续失败告警**：任一通道连续 3 次查询失败后发送 Bark 告警；持续失败期间不会重复轰炸。
- **恢复通知**：已经触发失败告警的通道重新查询成功后，会发送 Bark 恢复通知并清除故障状态。
- **IPv4 / IPv6 控制**：默认只监控 IPv4，避免不同探测源返回不同地址族导致假变更。
- **可靠通知**：IP 变化后如果 Bark 推送失败，不会提前提交新 IP；下一轮继续重试。
- **旧缓存兼容**：升级前的 `last_ip` 自动作为国外出口 IP 的历史基线。
- **状态持久化**：`.ip_cache.json` 保存国内 / 国外 IP、最近历史以及连续失败状态，因此 launchd 每次重新启动 `--once` 也能累计失败次数。
- **macOS launchd**：默认每 5 分钟自动执行一次单次检查，无需常驻 Python 进程。
- **自动化测试**：`pytest` + `respx`。

## ⚠️ 关于“真实国内 IP”

国内 IP 检测的原理是：访问国内检测域名，并让代理软件在**规则模式**下把这些域名走 `DIRECT`；海外检测域名则继续走代理。

如果代理软件开启了**全局代理**，或者 TUN 规则强制所有流量都经过代理，那么国内和国外检测结果可能相同。这种情况下程序本身无法从同一条被强制代理的网络路径中恢复运营商真实出口 IP。

默认国内检测源包括：

```text
https://4.ipw.cn
https://6.ipw.cn
https://cip.cc
http://myip.ipip.net
```

建议在 Mihomo / Clash 等代理规则中确保这些国内检测域名走 `DIRECT`。

## 🚀 快速开始

```bash
cp .env.example .env
```

编辑 `.env`：

```ini
BARK_KEY=YOUR_BARK_DEVICE_KEY
CHECK_INTERVAL=60
IP_VERSION=4
NOTIFY_ON_START=true
```

`IP_VERSION`：

- `4`：只监控 IPv4（默认）
- `6`：只监控 IPv6
- `any`：接受 IPv4 或 IPv6

如需自定义检测源：

```ini
DOMESTIC_IP_PROVIDERS=["https://4.ipw.cn","https://cip.cc"]
IP_PROVIDERS=["https://api.ipify.org","https://icanhazip.com"]
```

> `IP_PROVIDERS` 继续沿用原变量名，现在表示国外 / 代理出口 IP 检测源。

## 运行

```bash
# 诊断国内 / 国外 IP 源并测试 Bark
uv run update-ip --test

# 单次检查：同时显示国内与国外 IP
uv run update-ip --once

# 查看两个 IP 的缓存和历史
uv run update-ip --status

# 持续运行
uv run update-ip
```

`--once` 输出示例：

```text
Domestic IP: 1.2.3.4 (Unchanged)
Foreign IP: 203.0.113.20 (Unchanged)
```

临时指定地址族：

```bash
uv run update-ip --ip-version 6
```

## macOS 每 5 分钟自动检查

直接使用三个命令控制：

```bash
# 开启：自动生成/刷新 LaunchAgent，并每 5 分钟检查一次
uv run update-ip start

# 关闭
uv run update-ip stop

# 查询是否启用
uv run update-ip service-status
```

任务会在加载时检查一次，之后由 macOS 每 5 分钟执行一次 `update-ip --once`，每次都会同时检查国内与国外 IP。

如果某个通道连续 3 次失败（默认 5 分钟一次时约为连续 15 分钟失败），会发送一次 Bark 告警；之后继续失败不会重复发送。该通道下一次查询成功时，会再发送一次恢复通知。

如需改为其他间隔，例如 10 分钟：

```bash
uv run update-ip start --launchd-interval 600
```

> `CHECK_INTERVAL` 用于 `uv run update-ip` 的常驻运行模式；launchd 定时模式使用 `--launchd-interval`。

如只想生成 plist、不立即开启：

```bash
uv run update-ip --generate-launchd
```

查看日志：

```bash
tail -f logs/stdout.log
tail -f logs/stderr.log
```

## 常用参数

| 参数 / 命令 | 简写 | 描述 |
| :--- | :--- | :--- |
| `start` | | 开启 macOS 每 5 分钟自动检查 |
| `stop` | | 关闭 macOS 自动检查 |
| `service-status` | | 查询 macOS 定时任务状态 |
| `--key` | `-k` | 覆盖 Bark device key |
| `--server` | `-s` | 自定义 Bark 服务器 |
| `--interval` | `-i` | 常驻模式检查间隔秒数，必须 >= 1 |
| `--ip-version` | | `4` / `6` / `any` |
| `--config` | `-c` | 指定自定义 `.env` |
| `--once` | | 同时检查国内 / 国外 IP 后退出 |
| `--test` | | 两组 IP 源与 Bark 诊断 |
| `--status` | | 查看两个 IP 的缓存和历史 |
| `--generate-launchd` | | 只生成 macOS LaunchAgent |
| `--launchd-interval` | | launchd 定时间隔秒数，默认 `300` |
| `--no-notify-on-start` | | 启动时不发送就绪通知 |
| `--verbose` | `-v` | Debug 日志 |

## 测试

```bash
uv run pytest -v
```
