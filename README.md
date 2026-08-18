# 🌐 IP 变动监控与 Bark 实时推送

一个基于 **Python 3.13** 和 **uv** 构建的公网 IP 变动监控与 Bark 实时推送工具。

当你的网络公网 IP 发生变动（例如宽带重新拨号、家庭宽带租期刷新、Wi-Fi/热点切换等）时，脚本会立即捕获变动并向你的 iPhone/iPad 推送 Bark 通知。

---

## ✨ 核心特性

- ⚡ **轻量高效**：基于 Python 3.13 异步协程 (`asyncio` + `httpx`) 构建，CPU 与内存占用极低。
- 🛡 **多源冗余容灾**：内置 7 个知名高可用公网 IP 探测源（ipify, icanhazip, ifconfig.me, ident.me, ip.sb, cip.cc 等），单点接口故障自动无缝切换。
- 💾 **状态智能持久化**：本地维护 `.ip_cache.json` 状态与历史变更记录，脚本重启不会误报虚假变动。
- 🔔 **Bark 深度定制**：支持自定义 Bark 推送标题、分组（Group）、声音（Sound）、图标（Icon）、跳转链接及通知优先级（active / timeSensitive / passive）。
- 🛠 **开箱即用 & 易于守护**：内置一键生成 macOS `launchd` 自启守护服务，开机自启且崩溃自动拉起。
- 🧪 **完整测试套件**：配备 `pytest` + `respx` 单元测试与网络 Mock 测试。

---

## 🚀 快速开始

### 1. 配置 Bark Key

拷贝或直接编辑 `.env` 文件，填入你的 Bark 设备 Key：

```bash
# 编辑 .env 文件
cp .env.example .env
```

在 `.env` 中填入你的 Bark 设备 Key（在 iOS Bark App 中即可复制）：

```ini
# Bark 设备 Key
BARK_KEY=YOUR_BARK_DEVICE_KEY

# 检查间隔时间（秒，默认 60 秒）
CHECK_INTERVAL=60

# 启动时是否发送一条确认通知
NOTIFY_ON_START=true

# 提示音 (可选: minuet, bell, alarm, electronic, glass 等)
BARK_SOUND=minuet
```

---

### 2. 测试与运行

#### 诊断网络与测试 Bark 推送
```bash
uv run update-ip --test
# 或者
uv run python main.py --test
```

#### 单次运行（用于 Cron 计划任务或排查）
```bash
uv run update-ip --once
```

#### 查看当前缓存的 IP 与变动历史
```bash
uv run update-ip --status
```

#### 持续前台监控运行
```bash
uv run update-ip
```

---

## 🖥️ macOS 后台自启服务（开机静默运行）

本项目内置了 macOS `launchd` 服务配置生成器：

### 1. 生成并安装服务
```bash
uv run update-ip --generate-launchd
```

该命令会在 `~/Library/LaunchAgents/com.update-ip.monitor.plist` 生成自启服务文件。

### 2. 启动服务
```bash
launchctl load -w ~/Library/LaunchAgents/com.update-ip.monitor.plist
```

### 3. 查看运行日志
```bash
tail -f logs/stdout.log
tail -f logs/stderr.log
```

### 4. 停止并卸载服务
```bash
launchctl unload -w ~/Library/LaunchAgents/com.update-ip.monitor.plist
```

---

## ⚙️ 命令行参数一览

| 参数 | 简写 | 描述 |
| :--- | :--- | :--- |
| `--key` | `-k` | 覆盖配置中的 Bark 设备 Key |
| `--server` | `-s` | 自定义 Bark 服务器地址（默认 `https://api.day.app`） |
| `--interval` | `-i` | 检查间隔秒数（默认 60 秒） |
| `--config` | `-c` | 指定自定义 `.env` 配置文件路径 |
| `--once` | | 单次检查 IP，有变动则推送并更新缓存，然后退出 |
| `--test` | | 运行 IP 接口测试与 Bark 连通性测试 |
| `--status` | | 查看当前缓存 IP 及历史变动表格 |
| `--generate-launchd` | | 一键生成 macOS launchd 开机自启服务文件 |
| `--no-notify-on-start` | | 启动时不发送就绪通知 |
| `--verbose` | `-v` | 输出 Debug 级别详细日志 |

---

## 🧪 自动化测试

运行完整测试套件：

```bash
uv run pytest -v
```
