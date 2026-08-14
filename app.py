#!/usr/bin/env python3
"""Redroid Manager — 轻量 Android 容器管理面板"""

import os
import re
import json
import time
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, request, render_template, send_from_directory, Response
import docker

# ── Config ───────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
APK_DIR = BASE_DIR / "apk_uploads"
APK_DIR.mkdir(exist_ok=True)

REDROID_IMAGE = "redroid/redroid:15.0.0-latest"
LABEL_MANAGER = "redroid-manager"
LABEL_ADB_PORT = "redroid-manager.adb-port"
SCRCPY_PORT = 8000  # ws-scrcpy 端口

# ── Init ─────────────────────────────────────────────────────
app = Flask(__name__)
client = docker.from_env()


# ═══════════════════════════════════════════════════════════
#  Docker Helpers
# ═══════════════════════════════════════════════════════════

def get_redroid_containers(all=False):
    """获取所有 Redroid 管理容器"""
    containers = client.containers.list(all=all, filters={"label": LABEL_MANAGER})
    return containers


def build_instance_info(ct):
    """从容器对象提取展示信息"""
    name = ct.name
    status = ct.status
    started = ct.attrs["State"]["StartedAt"].split(".")[0].replace("T", " ") if ct.status == "running" else None
    adb_port = ct.labels.get(LABEL_ADB_PORT, "N/A")

    # 尝试获取 Android 属性
    android_ver = "—"
    booted = "—"
    if ct.status == "running":
        try:
            android_ver = ct.exec_run("getprop ro.build.version.release").output.decode().strip() or "—"
            booted = ct.exec_run("getprop sys.boot_completed").output.decode().strip()
            booted = "✅" if booted == "1" else "⏳"
        except Exception:
            pass

    # 容器指标
    try:
        stats = ct.stats(stream=False)
        cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
        system_delta = stats["cpu_stats"].get("system_cpu_usage", 0) - stats["precpu_stats"].get("system_cpu_usage", 0)
        cpu_pct = round((cpu_delta / system_delta) * 100, 1) if system_delta > 0 else 0
        mem_bytes = stats["memory_stats"].get("usage", 0)
        mem_mb = round(mem_bytes / 1024 / 1024, 0)
    except Exception:
        cpu_pct = 0
        mem_mb = 0

    return {
        "name": name,
        "status": status,
        "started": started,
        "adb_port": adb_port,
        "android_ver": android_ver,
        "booted": booted,
        "cpu_pct": cpu_pct,
        "mem_mb": mem_mb,
    }


def find_available_port():
    """查找可用 ADB 端口 (5555+)"""
    used = set()
    for ct in get_redroid_containers(all=True):
        p = ct.labels.get(LABEL_ADB_PORT)
        if p:
            used.add(int(p))
    port = 5555
    while port in used:
        port += 1
    return port


def get_adb_path():
    """查找 adb 可执行文件"""
    for p in [os.path.expanduser("~/.local/bin/adb"), "/usr/bin/adb", "/usr/local/bin/adb"]:
        if os.path.exists(p):
            return p
    # 尝试 which
    try:
        return subprocess.check_output(["which", "adb"]).decode().strip()
    except Exception:
        return "adb"


# ═══════════════════════════════════════════════════════════
#  API — 实例管理
# ═══════════════════════════════════════════════════════════

@app.route("/api/host/stats")
def host_stats():
    """宿主机资源"""
    containers = get_redroid_containers(all=True)
    running = sum(1 for c in containers if c.status == "running")
    return jsonify({
        "total": len(containers),
        "running": running,
        "stopped": len(containers) - running,
    })


@app.route("/api/instances")
def list_instances():
    """实例列表"""
    containers = get_redroid_containers(all=True)
    return jsonify([build_instance_info(ct) for ct in containers])


@app.route("/api/instances", methods=["POST"])
def create_instance():
    """创建新 Redroid 实例"""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    width = int(data.get("width", 720))
    height = int(data.get("height", 1280))
    dpi = int(data.get("dpi", 320))
    fps = int(data.get("fps", 30))
    adb_port = int(data.get("adb_port", 0)) or find_available_port()
    image = data.get("image", "").strip() or REDROID_IMAGE

    # 验证镜像格式
    if ":" not in image or "/" not in image:
        # 如果传的是简写 (如 "15"), 补全为完整镜像名
        known = {e["android"]: e["image"] for e in KNOWN_IMAGES}
        image = known.get(image, REDROID_IMAGE)

    # 自动生成名称
    if not name:
        existing = [c.name for c in get_redroid_containers(all=True)]
        n = 1
        while f"phone_{n}" in existing:
            n += 1
        name = f"phone_{n}"

    # 检查端口冲突
    for ct in get_redroid_containers(all=True):
        if ct.labels.get(LABEL_ADB_PORT) == str(adb_port):
            return jsonify({"error": f"ADB 端口 {adb_port} 已被占用"}), 409

    # 拉取镜像（如果不存在）
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        return jsonify({"error": f"镜像 {image} 未缓存，请先 docker pull {image}"}), 400

    # 启动容器
    container = client.containers.run(
        image=image,
        name=name,
        privileged=True,
        detach=True,
        ports={f"{adb_port}/tcp": adb_port},
        volumes={f"{name}-data": {"bind": "/data", "mode": "rw"}},
        command=[
            "androidboot.use_memfd=true",
            f"androidboot.redroid_width={width}",
            f"androidboot.redroid_height={height}",
            f"androidboot.redroid_dpi={dpi}",
            f"androidboot.redroid_fps={fps}",
            "androidboot.redroid_gpu_mode=auto",
        ],
        labels={
            LABEL_MANAGER: "1",
            LABEL_ADB_PORT: str(adb_port),
            "redroid-manager.width": str(width),
            "redroid-manager.height": str(height),
            "redroid-manager.dpi": str(dpi),
        },
    )

    return jsonify({
        "message": f"实例 {name} 创建成功",
        "adb_port": adb_port,
        **build_instance_info(container),
    }), 201


@app.route("/api/instances/<name>/<action>", methods=["POST"])
def instance_action(name, action):
    """实例操作: start / stop / restart"""
    try:
        ct = client.containers.get(name)
    except docker.errors.NotFound:
        return jsonify({"error": f"实例 {name} 不存在"}), 404

    if action == "start":
        ct.start()
    elif action == "stop":
        ct.stop()
    elif action == "restart":
        ct.restart()
    else:
        return jsonify({"error": f"未知操作: {action}"}), 400

    return jsonify({"message": f"{name} {action} 成功", "status": ct.status})


@app.route("/api/instances/<name>/clone", methods=["POST"])
def clone_instance(name):
    """克隆已有实例（相同参数，新名称，新ADB端口）"""
    try:
        src = client.containers.get(name)
    except docker.errors.NotFound:
        return jsonify({"error": f"实例 {name} 不存在"}), 404

    labels = src.labels
    src_image = src.attrs["Config"]["Image"]
    adb_port = find_available_port()

    # 读取源实例的启动参数
    src_cmd = src.attrs["Config"].get("Cmd", [])
    width = height = dpi = fps = None
    for cmd in src_cmd:
        if "redroid_width" in cmd:
            width = cmd.split("=")[1]
        elif "redroid_height" in cmd:
            height = cmd.split("=")[1]
        elif "redroid_dpi" in cmd:
            dpi = cmd.split("=")[1]
        elif "redroid_fps" in cmd:
            fps = cmd.split("=")[1]

    width = int(width) if width else 720
    height = int(height) if height else 1280
    dpi = int(dpi) if dpi else 320
    fps = int(fps) if fps else 30

    # 生成新名称
    existing = {c.name for c in get_redroid_containers(all=True)}
    n = 1
    while f"{name}_clone_{n}" in existing:
        n += 1
    new_name = f"{name}_clone_{n}"

    container = client.containers.run(
        image=src_image,
        name=new_name,
        privileged=True,
        detach=True,
        ports={f"{adb_port}/tcp": adb_port},
        volumes={f"{new_name}-data": {"bind": "/data", "mode": "rw"}},
        command=[
            "androidboot.use_memfd=true",
            f"androidboot.redroid_width={width}",
            f"androidboot.redroid_height={height}",
            f"androidboot.redroid_dpi={dpi}",
            f"androidboot.redroid_fps={fps}",
            "androidboot.redroid_gpu_mode=auto",
        ],
        labels={
            LABEL_MANAGER: "1",
            LABEL_ADB_PORT: str(adb_port),
        },
    )

    return jsonify({
        "message": f"克隆成功: {new_name}",
        "name": new_name,
        "adb_port": adb_port,
        **build_instance_info(container),
    }), 201


@app.route("/api/instances/<name>", methods=["DELETE"])
def delete_instance(name):
    """删除实例（含数据卷）"""
    try:
        ct = client.containers.get(name)
    except docker.errors.NotFound:
        return jsonify({"error": f"实例 {name} 不存在"}), 404

    ct.stop()
    ct.remove()
    # 清理数据卷
    try:
        vol = client.volumes.get(f"{name}-data")
        vol.remove()
    except Exception:
        pass

    return jsonify({"message": f"实例 {name} 已删除"})


@app.route("/api/instances/<name>/stats")
def instance_stats(name):
    """实例实时指标"""
    try:
        ct = client.containers.get(name)
    except docker.errors.NotFound:
        return jsonify({"error": f"实例 {name} 不存在"}), 404
    return jsonify(build_instance_info(ct))


# ═══════════════════════════════════════════════════════════
#  API — APK 管理
# ═══════════════════════════════════════════════════════════

@app.route("/api/apk/list")
def apk_list():
    """已上传 APK 列表"""
    files = []
    for f in sorted(APK_DIR.glob("*.apk"), key=lambda x: x.stat().st_mtime, reverse=True):
        files.append({
            "name": f.name,
            "size_mb": round(f.stat().st_size / 1024 / 1024, 2),
            "uploaded": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return jsonify(files)


@app.route("/api/apk/upload", methods=["POST"])
def apk_upload():
    """上传 APK"""
    file = request.files.get("file")
    if not file or not file.filename.endswith(".apk"):
        return jsonify({"error": "请上传 .apk 文件"}), 400
    safe_name = re.sub(r"[^\w\.\-]", "_", file.filename)
    file.save(APK_DIR / safe_name)
    return jsonify({"message": f"{safe_name} 上传成功", "name": safe_name})


# ── Install Jobs (background + progress) ──────────────────────────
import threading
install_jobs = {}  # job_id -> {status, progress, results, message}

# ── Available Images ───────────────────────────────────────────────
KNOWN_IMAGES = [
    {"image": "redroid/redroid:10.0.0-latest", "android": "10", "desc": "Android 10"},
    {"image": "redroid/redroid:11.0.0-latest", "android": "11", "desc": "Android 11"},
    {"image": "redroid/redroid:12.0.0-latest", "android": "12", "desc": "Android 12"},
    {"image": "redroid/redroid:13.0.0-latest", "android": "13", "desc": "Android 13"},
    {"image": "redroid/redroid:14.0.0-latest", "android": "14", "desc": "Android 14"},
    {"image": "redroid/redroid:15.0.0-latest", "android": "15", "desc": "Android 15"},
    {"image": "redroid/redroid:16.0.0-latest", "android": "16", "desc": "Android 16"},
]


@app.route("/api/images")
def list_images():
    """返回可用镜像及其本地缓存状态"""
    local_tags = set()
    for img in client.images.list():
        for tag in img.tags:
            local_tags.add(tag)
    
    result = []
    for entry in KNOWN_IMAGES:
        cached = entry["image"] in local_tags
        result.append({**entry, "cached": cached})
    return jsonify(result)


def _get_packages(ct):
    """获取容器内已安装的第三方包名集合"""
    try:
        out = ct.exec_run("pm list packages -3").output.decode()
        return set(re.findall(r"package:(\S+)", out))
    except Exception:
        return set()


def _extract_pkg_name(apk_path):
    """从 APK 的二进制 AndroidManifest.xml 提取包名"""
    import struct as _struct, zipfile as _zipfile
    try:
        with _zipfile.ZipFile(apk_path) as z:
            data = z.read("AndroidManifest.xml")
        if len(data) < 36:
            return ""
        # AXML string pool header: type(2) + header(2) + chunk(4) + count(4) + style_count(4) + flags(4) + str_start(4) + style_start(4)
        string_count = _struct.unpack_from("<I", data, 8)[0]
        strings_start = _struct.unpack_from("<I", data, 20)[0]  # relative to pool start
        flags = _struct.unpack_from("<I", data, 16)[0]
        is_utf16 = (flags & 0x100) != 0
        offsets = [_struct.unpack_from("<I", data, 28 + i*4)[0] for i in range(min(string_count, 60))]
        for off in offsets:
            pos = strings_start + off
            if pos + 2 > len(data):
                continue
            if is_utf16:
                ln = _struct.unpack_from("<H", data, pos)[0]
                if ln & 0x8000:
                    ln = (ln & 0x7fff) * 2
                pos += 2
                raw = data[pos:pos+ln].decode("utf-16-le", errors="ignore") if ln > 0 else ""
            else:
                # UTF-8: length byte(s)
                ln = data[pos]
                pos += 1
                if ln & 0x80:
                    ln = ((ln & 0x7f) << 8) | data[pos]
                    pos += 1
                raw = data[pos:pos+ln].decode("utf-8", errors="ignore") if ln > 0 else ""
            if re.fullmatch(r"[a-zA-Z][\w]*(\.[a-zA-Z][\w]*)+", raw):
                return raw
    except Exception:
        pass
    return ""


def _do_install_one(ct, apk_path, apk_name):
    """安装单个 APK 到单个容器，返回 (status, msg, pkg)"""
    import io as _io, tarfile as _tarfile
    try:
        # 安装前快照
        before = _get_packages(ct)

        # Push via tar
        tarstream = _io.BytesIO()
        tar = _tarfile.open(fileobj=tarstream, mode='w')
        tar.add(apk_path, arcname=apk_name)
        tar.close()
        tarstream.seek(0)
        ct.put_archive("/data/local/tmp", tarstream)

        # Install with compatibility flags
        result = ct.exec_run(f"pm install -r -t -d /data/local/tmp/{apk_name}")
        output = result.output.decode().strip()

        if result.exit_code == 0 or "Success" in output:
            # 优先从 APK 提取包名
            pkg_name = _extract_pkg_name(apk_path)
            if not pkg_name:
                after = _get_packages(ct)
                new_pkgs = after - before
                pkg_name = ", ".join(new_pkgs) if new_pkgs else "unknown"
            return ("success", "安装成功", pkg_name)
        else:
            err = output[-200:] if len(output) > 200 else output
            return ("error", err, "")
    except Exception as e:
        return ("error", str(e)[:150], "")


@app.route("/api/apk/install", methods=["POST"])
def apk_install():
    """批量安装 APK（异步进度追踪）"""
    data = request.get_json() or {}
    apk_name = data.get("apk", "").strip()
    targets = data.get("targets", [])

    apk_path = APK_DIR / apk_name
    if not apk_path.exists():
        return jsonify({"error": f"APK {apk_name} 不存在"}), 404
    if not targets:
        return jsonify({"error": "未指定目标实例"}), 400

    job_id = f"install_{int(time.time())}_{apk_name}"
    install_jobs[job_id] = {
        "status": "running", "total": len(targets), "done": 0,
        "message": "开始安装...", "results": [], "apk": apk_name
    }

    def _run():
        results = []
        for i, name in enumerate(targets):
            install_jobs[job_id]["message"] = f"[{i+1}/{len(targets)}] {name}: 推送中..."
            try:
                ct = client.containers.get(name)
            except docker.errors.NotFound:
                results.append({"name": name, "status": "error", "msg": "不存在"})
                install_jobs[job_id]["done"] = i + 1
                continue

            if ct.status != "running":
                results.append({"name": name, "status": "error", "msg": "未运行"})
                install_jobs[job_id]["done"] = i + 1
                continue

            # Wait for boot
            install_jobs[job_id]["message"] = f"[{i+1}/{len(targets)}] {name}: 等待就绪..."
            for _ in range(40):
                try:
                    if ct.exec_run("getprop sys.boot_completed").output.decode().strip() == "1":
                        break
                except Exception:
                    pass
                time.sleep(3)

            # Install
            install_jobs[job_id]["message"] = f"[{i+1}/{len(targets)}] {name}: 安装中..."
            status, msg, pkg = _do_install_one(ct, apk_path, apk_name)
            entry = {"name": name, "status": status, "msg": msg}
            if pkg and status == "success":
                entry["package"] = pkg
            results.append(entry)
            install_jobs[job_id]["done"] = i + 1

        install_jobs[job_id]["status"] = "done"
        ok = sum(1 for r in results if r["status"] == "success")
        install_jobs[job_id]["message"] = f"完成: {ok}/{len(targets)} 成功"
        install_jobs[job_id]["results"] = results

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"job_id": job_id, "status": "accepted"}), 202


@app.route("/api/apk/install/<job_id>")
def apk_install_status(job_id):
    """查询安装进度"""
    job = install_jobs.get(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(job)


@app.route("/api/apk/<filename>", methods=["DELETE"])
def apk_delete(filename):
    """删除 APK 文件"""
    path = APK_DIR / filename
    if path.exists():
        path.unlink()
        return jsonify({"message": f"{filename} 已删除"})
    return jsonify({"error": "文件不存在"}), 404


# ═══════════════════════════════════════════════════════════
#  Frontend
# ═══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ═══════════════════════════════════════════════════════════
#  屏幕流 — MJPEG (浏览器直接显示)
# ═══════════════════════════════════════════════════════════

@app.route("/api/instances/<name>/screen")
def instance_screen(name):
    """MJPEG 屏幕流 — 浏览器 <img src> 直接显示"""
    try:
        ct = client.containers.get(name)
    except docker.errors.NotFound:
        return "实例不存在", 404

    if ct.status != "running":
        return "实例未运行", 400

    adb_port = ct.labels.get(LABEL_ADB_PORT, "")
    if not adb_port:
        return "未找到 ADB 端口", 400

    def generate():
        import time as time_mod
        frame_interval = 0.3  # ~3 FPS
        while True:
            try:
                # 通过 docker exec screencap 截图
                result = ct.exec_run("screencap -p")
                if result.exit_code == 0 and result.output:
                    # screencap 输出 PNG，直接封装为 MJPEG frame
                    png_data = result.output
                    # 找 PNG 起始 (strip any prefix text)
                    png_start = png_data.find(b'\x89PNG')
                    if png_start >= 0:
                        png_data = png_data[png_start:]
                    yield (b'--frame\r\n'
                           b'Content-Type: image/png\r\n\r\n' + png_data + b'\r\n')
                else:
                    time_mod.sleep(frame_interval)
                    continue
            except Exception:
                time_mod.sleep(frame_interval)
                continue

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route("/api/instances/<name>/input", methods=["POST"])
def instance_input(name):
    """转发触摸/按键到 Android 容器"""
    try:
        ct = client.containers.get(name)
    except docker.errors.NotFound:
        return jsonify({"error": f"实例 {name} 不存在"}), 404

    if ct.status != "running":
        return jsonify({"error": "实例未运行"}), 400

    data = request.get_json() or {}
    action = data.get("action", "")

    try:
        if action == "tap":
            x, y = int(data["x"]), int(data["y"])
            ct.exec_run(f"input tap {x} {y}")
        elif action == "swipe":
            x1, y1, x2, y2 = int(data["x1"]), int(data["y1"]), int(data["x2"]), int(data["y2"])
            ct.exec_run(f"input swipe {x1} {y1} {x2} {y2}")
        elif action == "key":
            ct.exec_run(f"input keyevent {int(data['code'])}")
        elif action == "text":
            # Escape special chars for shell
            text = data["text"].replace("'", "\\'")
            ct.exec_run(f"input text '{text}'")
        else:
            return jsonify({"error": f"未知操作: {action}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"Redroid Manager → http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)