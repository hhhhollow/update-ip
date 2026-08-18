# 🌐 IP 变动监控与 Bark 实时推送

基于 **Python 3.13** 和 **uv** 的公网 IP 变动监控工具；检测到变化后，通过 Bark 推送到 iPhone/iPad。

## ✨ 特性

- **多源容灾**：多个公网 IP 探测源自动切换。
- **指数退避重试**：单个探测源失败后不会立即高频重试。
- **IPv4 / IPv6 控制**：默认只监控 IPv4，避免不同探测源返回不同地址族导致假变更。
- **可靠通知**：IP 变化后如果 Bark 推送失败，不会提前提交新 IP；下一轮继续重试。
- **敏感信息保护**：Debug 日志不会输出 Bark device key。
- **状态持久化**：`.ip_cache.json` 保存当前 IP 与最近历史。
- **macOS launchd**：支持登录自启和崩溃拉起。
- **自动化测试**：`pytest` + `respx`。

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

## 运行

```bash
# 诊断 IP 源并测试 Bark
uv run update-ip --test

# 单次检查
uv run update-ip --once

# 查看缓存和历史
uv run update-ip --status

# 持续运行
uv run update-ip
```

临时指定地址族：

```bash
uv run update-ip --ip-version 6
```

## macOS 后台自启

```bash
uv run update-ip --generate-launchd
launchctl load -w ~/Library/LaunchAgents/com.update-ip.monitor.plist
```

查看日志：

```bash
tail -f logs/stdout.log
tail -f logs/stderr.log
```

停止：

```bash
launchctl unload -w ~/Library/LaunchAgents/com.update-ip.monitor.plist
```

## 常用参数

| 参数 | 简写 | 描述 |
| :--- | :--- | :--- |
| `--key` | `-k` | 覆盖 Bark device key |
| `--server` | `-s` | 自定义 Bark 服务器 |
| `--interval` | `-i` | 检查间隔秒数，必须 >= 1 |
| `--ip-version` | | `4` / `6` / `any` |
| `--config` | `-c` | 指定自定义 `.env` |
| `--once` | | 单次检查并退出 |
| `--test` | | IP 源与 Bark 诊断 |
| `--status` | | 查看缓存和历史 |
| `--generate-launchd` | | 生成 macOS LaunchAgent |
| `--no-notify-on-start` | | 启动时不发送就绪通知 |
| `--verbose` | `-v` | Debug 日志 |

## 测试

```bash
uv run pytest -v
```
