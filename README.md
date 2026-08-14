# 🤖 Redroid Manager

一个基于 Web 的 Android 容器（云手机）集群管理面板，用于在 Linux x86 主机上批量部署、管理和操控多个 [Redroid](https://github.com/remote-android/redroid-doc)（Android 容器化）实例。

A lightweight web-based management panel for deploying, managing, and controlling multiple [Redroid](https://github.com/remote-android/redroid-doc) (Android-in-Docker) instances on a Linux x86 host.

---

## ✨ 功能特性 (Features)

- 📱 **多实例管理** — 创建、启动、停止、重启、克隆、删除 Android 容器实例
- 🖥️ **浏览器实时投屏** — 无需安装客户端，网页直接查看和操控 Android 屏幕（MJPEG 流）
- 🎮 **完整触控交互** — 鼠标点击=触摸、拖动=滑动、滚轮=翻页、键盘=输入、虚拟导航键
- 📦 **APK 仓库管理** — 上传、删除、批量安装 APK，带实时进度条
- 🅰️ **多版本镜像支持** — 创建实例时可选 Android 10~16 版本，标注本地缓存状态
- 📊 **实时资源监控** — CPU/内存使用率、运行状态自动刷新
- 🔌 **ADB 端口透传** — 一键复制 `adb connect` 命令

---

## 🏗️ 架构 (Architecture)

```
┌─────────────────────────────────────────┐
│              浏览器 (Browser)             │
│         http://localhost:5000            │
│  ┌────────────────────────────────────┐  │
│  │ 仪表盘 │ APK仓库 │ 实例列表 │ 投屏  │  │
│  └────────────────────────────────────┘  │
└──────────────────┬──────────────────────┘
                   │ REST API + MJPEG
┌──────────────────▼──────────────────────┐
│           Flask (app.py)                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Docker   │ │  ADB     │ │  APK     │ │
│  │ SDK      │ │ Bridge   │ │ Store    │ │
│  └────┬─────┘ └────┬─────┘ └──────────┘ │
└───────┼────────────┼─────────────────────┘
        │            │
┌───────▼────────────▼─────────────────────┐
│           Docker Engine                  │
│  ┌────────┐ ┌────────┐ ┌────────┐       │
│  │phone_1 │ │phone_2 │ │phone_N │       │
│  │Android │ │Android │ │Android │       │
│  │ :5555  │ │ :5556  │ │ :5555+N│       │
│  └────────┘ └────────┘ └────────┘       │
│         Redroid Containers              │
└──────────────────────────────────────────┘
```

---

## 📦 项目结构 (Project Structure)

```
RedroidManager/
├── app.py                    # Flask 后端主程序（API + Docker 操作 + ADB 桥接 + 屏幕流）
├── templates/
│   └── index.html            # 前端单页应用（HTML + CSS + Vanilla JS）
├── start.sh                  # 一键启动脚本
├── requirements.txt          # Python 依赖
├── apk_uploads/              # APK 上传存储目录（运行时生成）
└── README.md                 # 本文档
```

---

## 🚀 快速开始 (Quick Start)

### 环境要求 (Requirements)

| 依赖 | 版本/说明 |
|------|-----------|
| Linux | 需加载 `binder_linux` 内核模块 |
| Docker | 需能访问 Docker Engine API |
| Python | 3.10+ |
| Redroid 镜像 | `redroid/redroid:15.0.0-latest`（或其它版本） |

### 1. 加载内核模块

```bash
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"

# 开机自动加载
echo "binder_linux" | sudo tee /etc/modules-load.d/redroid.conf
echo 'options binder_linux devices="binder,hwbinder,vndbinder"' | sudo tee /etc/modprobe.d/redroid.conf
```

### 2. 拉取基础镜像

```bash
docker pull redroid/redroid:15.0.0-latest
# 或通过国内镜像加速
docker pull docker.m.daocloud.io/redroid/redroid:15.0.0-latest
docker tag docker.m.daocloud.io/redroid/redroid:15.0.0-latest redroid/redroid:15.0.0-latest
```

### 3. 安装依赖并启动

```bash
# 克隆项目
git clone https://github.com/JinHisAndy/RedroidManager.git
cd RedroidManager

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 启动
bash start.sh
```

### 4. 访问面板

浏览器打开 `http://localhost:5000`（局域网访问 `http://<主机IP>:5000`）

---

## 📡 API 接口 (API Reference)

### 实例管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/instances` | 实例列表 |
| POST | `/api/instances` | 创建实例 |
| POST | `/api/instances/<name>/start` | 启动 |
| POST | `/api/instances/<name>/stop` | 停止 |
| POST | `/api/instances/<name>/restart` | 重启 |
| POST | `/api/instances/<name>/clone` | 克隆实例 |
| DELETE | `/api/instances/<name>` | 删除实例（含数据卷） |
| GET | `/api/instances/<name>/screen` | MJPEG 屏幕流 |
| POST | `/api/instances/<name>/input` | 触摸/按键输入 |

### APK 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/apk/list` | APK 列表 |
| POST | `/api/apk/upload` | 上传 APK |
| POST | `/api/apk/install` | 批量安装（异步，返回 job_id） |
| GET | `/api/apk/install/<job_id>` | 查询安装进度 |
| DELETE | `/api/apk/<filename>` | 删除 APK |

### 镜像管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/images` | 可用镜像列表（含缓存状态） |
| GET | `/api/host/stats` | 宿主机统计 |

### 输入操作格式 (Input Payload)

```json
{ "action": "tap",   "x": 360, "y": 640 }
{ "action": "swipe", "x1": 100, "y1": 500, "x2": 100, "y2": 200 }
{ "action": "key",   "code": 3 }        // keyevent
{ "action": "text",  "text": "hello" }
```

---

## 🎮 投屏操作说明 (Screen Control)

| 操作 | 效果 |
|------|------|
| 鼠标单击 | 触摸点击 |
| 鼠标拖动 | 滑动（swipe） |
| 鼠标滚轮 | 上下滑动翻页 |
| 键盘输入 | 文字输入 |
| ◀ ● ■ 按钮 | 返回 / 主页 / 多任务 |
| ↻ 按钮 | 横竖屏切换 |
| ESC 键 | 关闭投屏 |

---

## ⚠️ 常见问题 (FAQ)

### 1. 实例一直显示"启动中"

Android 16 镜像在 `guest` GPU 模式下 surfaceflinger 会崩溃。**解决方案**：使用 Android 15 或更早版本，GPU 模式用 `auto`。

### 2. ARM 架构的 APK 无法运行

Redroid 运行在 x86 架构，ARM 专属的 `.so` 库无法加载。报错信息：
```
UnsatisfiedLinkError: dlopen failed: ... is for EM_AARCH64 (183) instead of EM_X86_64 (62)
```
**解决方案**：安装 `libndk_translation`（ARM→x86 二进制翻译层），或寻找 x86 版本的 APK。

### 3. APK 安装后找不到应用

APK 的包名可能与文件名不同（如 `uuyc_4.36.0.apk` 的包名是 `com.netease.uuremote`）。安装结果弹窗会显示实际包名。

### 4. Docker 镜像拉取失败

Docker Hub 可能被墙，使用国内镜像加速：
```bash
sudo tee /etc/docker/daemon.json << 'EOF'
{ "registry-mirrors": ["https://docker.m.daocloud.io"] }
EOF
sudo systemctl restart docker
```

---

## 🔧 技术栈 (Tech Stack)

| 层 | 技术 |
|----|------|
| 后端 | Python Flask + docker-py |
| 前端 | 原生 HTML + CSS + Vanilla JS（零构建） |
| 容器 | Docker + Redroid |
| 屏幕流 | MJPEG (multipart/x-mixed-replace) |
| 输入 | ADB (input tap/swipe/keyevent/text) |

---

## 📄 许可证 (License)

MIT License

---

## 🤝 贡献 (Contributing)

欢迎提交 Issue 和 Pull Request。
