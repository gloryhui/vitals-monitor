"""Optional collectors and persistent incident transitions for the status page.

Standard library only. Checks are configured on the server, never from HTTP.
"""
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from .auth import validate_username
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class UnsupportedCollector(Exception):
    """This environment does not expose a metric; it is not an outage."""


DEFAULT_CONFIG = {
    "services": [],
    # Samples, collector archives and events older than this are deleted.
    "retention_days": 90,
    "auth": {
        "session_hours": 12,
        "admin_user": "admin",
        # Leave unset to have the first start generate a random password.
        "admin_password": None,
        "secure_cookie": False,
        "max_failures": 8,
        "failure_window_seconds": 600,
    },
    "alerts": {
        "cpu_percent": 90, "cpu_recovery_percent": 80, "cpu_hold_seconds": 60,
        "memory_percent": 90, "memory_recovery_percent": 85, "memory_hold_seconds": 60,
        "filesystem_percent": 90, "filesystem_recovery_percent": 85, "filesystem_hold_seconds": 30,
        "recovery_seconds": 30, "service_failures": 3, "service_recoveries": 2,
        "cpu_temperature": 85, "temperature_hold_seconds": 10,
    },
}


def load_configuration(path):
    config = copy.deepcopy(DEFAULT_CONFIG)
    path = Path(path)
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            supplied = json.load(handle)
        if not isinstance(supplied, dict):
            raise ValueError("配置必须是 JSON 对象")
        config["services"] = supplied.get("services", [])
        config["retention_days"] = supplied.get("retention_days", DEFAULT_CONFIG["retention_days"])
        config["auth"].update(supplied.get("auth", {}))
        config["alerts"].update(supplied.get("alerts", {}))
    if not isinstance(config["services"], list) or len(config["services"]) > 20:
        raise ValueError("服务检查必须为列表，最多 20 项")
    if (not isinstance(config["retention_days"], int) or isinstance(config["retention_days"], bool)
            or not 1 <= config["retention_days"] <= 3650):
        raise ValueError("数据保留天数必须是 1-3650 之间的整数")
    auth = config["auth"]
    if not isinstance(auth, dict):
        raise ValueError("auth 配置必须是 JSON 对象")
    unknown = set(auth) - set(DEFAULT_CONFIG["auth"])
    if unknown:
        raise ValueError("未知的 auth 配置: " + ", ".join(sorted(unknown)))
    hours = auth["session_hours"]
    if not isinstance(hours, (int, float)) or isinstance(hours, bool) or not math.isfinite(hours) or not 0.1 <= hours <= 720:
        raise ValueError("auth.session_hours 必须在 0.1-720 之间")
    if not isinstance(auth["secure_cookie"], bool):
        raise ValueError("auth.secure_cookie 必须是布尔值")
    failures = auth["max_failures"]
    if not isinstance(failures, int) or isinstance(failures, bool) or not 1 <= failures <= 1000:
        raise ValueError("auth.max_failures 必须是 1-1000 的整数")
    window = auth["failure_window_seconds"]
    if not isinstance(window, (int, float)) or isinstance(window, bool) or not math.isfinite(window) or not 30 <= window <= 86400:
        raise ValueError("auth.failure_window_seconds 必须在 30-86400 之间")
    validate_username(auth["admin_user"])
    if auth["admin_password"] is not None:
        if not isinstance(auth["admin_password"], str) or not 8 <= len(auth["admin_password"]) <= 200:
            raise ValueError("auth.admin_password 至少需要 8 个字符，或设为 null 自动生成")
    ids = set()
    for check in config["services"]:
        if not isinstance(check, dict) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(check.get("id", ""))):
            raise ValueError("每个服务检查需要一个有效 id")
        if check["id"] in ids:
            raise ValueError("服务检查 id 不能重复")
        ids.add(check["id"])
        kind = check.get("type")
        if kind == "systemd":
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", check.get("unit", "")):
                raise ValueError("systemd 检查需要有效的 .service 单元名")
        elif kind == "http":
            url = urlsplit(check.get("url", ""))
            if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
                raise ValueError("HTTP 检查需要无内嵌凭据的 http/https 地址")
        elif kind == "tcp":
            if not isinstance(check.get("host"), str) or not check["host"] or not isinstance(check.get("port"), int) or not 1 <= check["port"] <= 65535:
                raise ValueError("TCP 检查需要主机和 1-65535 的端口")
        else:
            raise ValueError("检查类型仅支持 systemd、http、tcp")
        timeout = check.get("timeout", 2)
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 5:
            raise ValueError("检查超时必须在 0-5 秒之间")
    for key, value in config["alerts"].items():
        if key not in DEFAULT_CONFIG["alerts"] or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("告警阈值无效: " + key)
    for name in ("cpu", "memory", "filesystem"):
        if not 0 <= config["alerts"][name + "_recovery_percent"] < config["alerts"][name + "_percent"] <= 100:
            raise ValueError("恢复阈值必须小于触发阈值，且在 0-100 之间")
    for name in ("service_failures", "service_recoveries"):
        if not isinstance(config["alerts"][name], int) or config["alerts"][name] < 1:
            raise ValueError("连续检查次数必须为正整数")
    return config


def require_tool(name):
    if shutil.which(name) is None:
        raise UnsupportedCollector(f"未安装 {name}，当前环境不采集此项")


def detect_environment(read_text, run):
    vendor = read_text("/sys/class/dmi/id/sys_vendor").strip()
    product = read_text("/sys/class/dmi/id/product_name").strip()
    hint = (vendor + " " + product).lower()
    virt = ""
    if shutil.which("systemd-detect-virt"):
        try:
            virt = run(["systemd-detect-virt"], timeout=2, allow_nonzero=True).strip()
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
    if virt == "none":
        virt = ""
    container = virt in ("docker", "podman", "lxc", "lxc-libvirt", "systemd-nspawn", "container-other")
    provider = "阿里云" if "alibaba" in hint or "aliyun" in hint else None
    return {"kind": "container" if container else "vm" if virt or provider else "physical",
            "label": "容器环境" if container else "虚拟机" if virt or provider else "物理机",
            "provider": provider, "virtualization": virt or None}


class ProcessSampler:
    def __init__(self, root="/proc", clock=time.monotonic):
        self.root = Path(root)
        self.clock = clock
        self.previous = {}
        self.previous_time = None
        self.hz = os.sysconf("SC_CLK_TCK")
        self.page_size = os.sysconf("SC_PAGE_SIZE")

    def collect(self):
        now = self.clock()
        elapsed = now - self.previous_time if self.previous_time is not None else None
        total_memory = 0
        for line in (self.root / "meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total_memory = int(line.split()[1]) * 1024
                break
        previous, rows = {}, []
        for directory in self.root.iterdir():
            if not directory.name.isdigit():
                continue
            try:
                stat = (directory / "stat").read_text()
                left, right = stat.index("("), stat.rindex(")")
                fields = stat[right + 2:].split()
                ticks = int(fields[11]) + int(fields[12])
                key = (int(directory.name), int(fields[19]))
                previous[key] = ticks
                delta = ticks - self.previous.get(key, ticks)
                usage = round(delta / self.hz / elapsed * 100, 1) if key in self.previous and elapsed and elapsed > 0 and delta >= 0 else None
                rss = max(0, int(fields[21])) * self.page_size
                rows.append({"pid": key[0], "name": stat[left + 1:right][:100], "cpu_percent": usage,
                             "rss_bytes": rss, "memory_percent": round(rss / total_memory * 100, 1) if total_memory else None})
            except (OSError, ValueError, IndexError):
                # Processes may exit or become unreadable between directory and stat reads.
                continue
        if not rows:
            raise RuntimeError("无法读取进程信息")
        self.previous, self.previous_time = previous, now
        return {"cpu": sorted(rows, key=lambda p: (p["cpu_percent"] if p["cpu_percent"] is not None else -1, p["rss_bytes"]), reverse=True)[:5],
                "memory": sorted(rows, key=lambda p: p["rss_bytes"], reverse=True)[:5],
                "count": len(rows), "cpu_basis": "one_core", "window_seconds": round(elapsed, 2) if elapsed else None}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ServiceChecker:
    def __init__(self, checks, run):
        self.checks = [dict(c) for c in checks if c.get("enabled", True)]
        self.run = run
        self.failures = {}
        # Do not follow redirects or environment proxies to unintended destinations.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def check(self, config):
        started = time.monotonic()
        kind = config["type"]
        result = {"id": config["id"], "name": config.get("name") or config["id"], "type": kind,
                  "ok": False, "detail": "", "checked_at": time.time()}
        try:
            if kind == "systemd":
                raw = self.run(["systemctl", "show", config["unit"], "--property=LoadState,ActiveState,SubState", "--no-pager"], timeout=config.get("timeout", 2))
                state = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
                result["ok"] = state.get("LoadState") == "loaded" and state.get("ActiveState") == "active"
                result["detail"] = "运行中" if result["ok"] else "未找到服务" if state.get("LoadState") == "not-found" else "服务未运行"
                result["target"] = config["unit"]
            elif kind == "http":
                url = urlsplit(config["url"])
                result["target"] = url.netloc + url.path
                request = Request(config["url"], headers={"User-Agent": "vitals-monitor/1.0", "Range": "bytes=0-0"})
                try:
                    response = self.opener.open(request, timeout=config.get("timeout", 2))
                except HTTPError as error:
                    response = error
                with response:
                    result["http_status"] = response.code
                    result["ok"] = 200 <= response.code < 400
                    result["detail"] = f"HTTP {response.code}" + (" · 跳转响应" if 300 <= response.code < 400 else "")
            else:
                result["target"] = f"{config['host']}:{config['port']}"
                with socket.create_connection((config["host"], config["port"]), timeout=config.get("timeout", 2)):
                    result["ok"] = True
                    result["detail"] = "端口可连接"
        except Exception as exc:
            # Do not expose full URLs, query credentials or command output in the UI.
            result["detail"] = "检查超时" if isinstance(exc, (TimeoutError, socket.timeout)) else "无法连接或读取状态"
        result["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
        return result

    def collect(self):
        if not self.checks:
            return []
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(self.check, self.checks))
        for row in rows:
            count = 0 if row["ok"] else self.failures.get(row["id"], 0) + 1
            self.failures[row["id"]] = count
            row["consecutive_failures"] = count
        return rows


def observations(snapshot, groups, alerts):
    result = []
    def add(key, stamp, bad, recovered, label, message, category="resource", severity="warning", hold=0, count=1, recovery_hold=0, recovery_count=1, interval=1):
        result.append({"key": key, "stamp": stamp, "bad": bool(bad), "recovered": bool(recovered),
                       "label": label, "message": message, "category": category, "severity": severity,
                       "hold": hold, "count": count, "recovery_hold": recovery_hold,
                       "recovery_count": recovery_count, "interval": interval})
    now = time.time()
    if snapshot and 0 <= now - snapshot.get("sampled_at", 0) < 5:
        for name, value in (("cpu", snapshot.get("cpu", {}).get("usage_percent")), ("memory", snapshot.get("memory", {}).get("used_percent"))):
            if isinstance(value, (int, float)):
                label = "CPU 使用率" if name == "cpu" else "内存使用率"
                add(name, snapshot["sampled_at"], value >= alerts[name + "_percent"], value <= alerts[name + "_recovery_percent"], label,
                    f"{label} {value:.1f}%，告警阈值 {alerts[name + '_percent']}%", hold=alerts[name + "_hold_seconds"], recovery_hold=alerts["recovery_seconds"])
    labels={'temperatures':'温度','smart':'磁盘健康','filesystems':'分区容量','containers':'容器','docker_usage':'Docker 空间','network_info':'网络信息','system':'系统信息','processes':'进程排行','services':'服务检查'}
    if snapshot:
        stale = now - snapshot.get('sampled_at',0) >= 5
        add('collector:sampler', now if stale else snapshot['sampled_at'], stale, not stale,
            '实时采样', '实时采样已中断', category='collector', hold=5, recovery_count=2)
    for name, group in groups.items():
        if group.get("available") is False:
            continue
        stamp = group.get("attempted_at")
        if stamp is None:
            continue
        if now - stamp > max(15, group["interval_seconds"] * 2.5):
            add("collector:"+name, now, True, False, labels.get(name,name)+'采集',
                labels.get(name,name)+'采集长时间未更新', category='collector', hold=60, recovery_count=2)
            continue
        add("collector:" + name, stamp, bool(group.get("error")), not group.get("error"), labels.get(name,name)+'采集', f"{labels.get(name,name)}数据采集连续失败", category="collector", hold=60, recovery_count=2, interval=group["interval_seconds"])
        if group["stale"] or group.get("data") is None:
            continue
        rows = group["data"]
        if name == "services":
            for item in rows:
                add("service:" + item["id"], stamp, not item["ok"], item["ok"], item["name"], f"{item['name']}：{item['detail']}", category="service", count=alerts["service_failures"], recovery_count=alerts["service_recoveries"], interval=15)
        elif name == "filesystems":
            for item in rows:
                value = item["used_percent"]
                add("filesystem:" + item["mount"], stamp, value >= alerts["filesystem_percent"], value <= alerts["filesystem_recovery_percent"], item["mount"], f"{item['mount']} 空间使用率 {value}%", category="disk", hold=alerts["filesystem_hold_seconds"], recovery_hold=30, interval=30)
        elif name == "containers":
            for item in rows:
                bad = item.get("health") == "unhealthy" or item["state"] in ("dead", "restarting")
                recovered = item["state"] == "running" and item.get("health") not in ("unhealthy", "starting")
                add("container:" + item["name"], stamp, bad, recovered, item["name"], f"容器 {item['name']} 健康异常或反复重启", category="container", count=3, recovery_count=2, interval=15)
        elif name == "smart":
            for item in rows:
                if item.get("standby") or item.get("error") or item.get("passed") is None:
                    continue
                bad = item["passed"] is False or any((item.get(k) or 0) > 0 for k in ("pending_sectors", "uncorrectable_sectors", "media_errors"))
                add("smart:" + item["device"], stamp, bad, not bad, item["device"], f"{item['device']} 磁盘健康需要关注", category="disk", severity="critical", interval=60)
        elif name == "temperatures":
            for item in rows:
                critical = item.get("critical")
                cpu = bool(re.search("cpu|k10temp|coretemp", item["chip"], re.I))
                threshold = critical if isinstance(critical, (int, float)) else alerts["cpu_temperature"] if cpu else None
                if threshold is None:
                    continue
                add("temperature:" + item["chip"] + ":" + item["label"], stamp, item["value"] >= threshold, item["value"] <= threshold - 5,
                    item["label"], f"{item['label']} 温度 {item['value']} °C，阈值 {threshold} °C", category="temperature", hold=alerts["temperature_hold_seconds"], recovery_hold=10, interval=5)
    return result


class EventEngine:
    """Debounce by distinct observations and store transitions atomically.

    Hysteresis, pending state and active incidents survive restarts. Unknown or
    unsupported metrics do not manufacture a recovery. No notification is sent.
    """
    def __init__(self, store):
        self.store = store
        self.states = store.load_incident_states()
        self.persisted = set(self.states)
        self.seen = {key: value.get("last_seen", 0) for key, value in self.states.items()}

    def evaluate(self, items):
        changed, events, seen = {}, [], dict(self.seen)
        for item in items:
            key, stamp = item["key"], item["stamp"]
            if stamp <= seen.get(key, -1):
                continue
            seen[key] = stamp
            state = copy.deepcopy(self.states.get(key, {"active": False, "bad_since": None, "good_since": None, "bad_count": 0, "good_count": 0}))
            if stamp - state.get("last_seen", stamp) > max(5, item["interval"] * 3):
                state.update(good_since=None, good_count=0)
                if not state['active']:
                    state.update(bad_since=None, bad_count=0)
            state.update(last_seen=stamp, key=key, label=item["label"], category=item["category"], severity=item["severity"], message=item["message"], interval=item['interval'])
            if not state["active"]:
                if item["bad"]:
                    if state["bad_since"] is None:
                        state["bad_since"] = stamp
                    state["bad_count"] += 1
                    if state["bad_count"] >= item["count"] and stamp - state["bad_since"] >= item["hold"]:
                        state.update(active=True, opened_at=stamp, good_since=None, good_count=0)
                        events.append(self.event(state, "triggered", stamp))
                else:
                    state.update(bad_since=None, bad_count=0)
            else:
                if item["recovered"]:
                    if state["good_since"] is None:
                        state["good_since"] = stamp
                    state["good_count"] += 1
                    if state["good_count"] >= item["recovery_count"] and stamp - state["good_since"] >= item["recovery_hold"]:
                        events.append(self.event(state, "recovered", stamp))
                        state.update(active=False, bad_since=None, good_since=None, bad_count=0, good_count=0)
                else:
                    state.update(good_since=None, good_count=0)
            if key in self.persisted or state["active"] or state["bad_since"] is not None:
                changed[key] = state
        if changed:
            # Do not publish in-memory state or observation tokens before commit.
            self.store.commit_events(changed, events)
            self.states.update(changed)
            self.persisted.update(changed)
        self.seen = seen

    @staticmethod
    def event(state, phase, stamp):
        return {"key": state["key"], "occurred_at": stamp, "phase": phase,
                "category": state["category"], "label": state["label"],
                "severity": state["severity"], "message": state["message"] if phase == "triggered" else state["label"] + " 已恢复",
                "started_at": state["bad_since"], "duration_seconds": max(0, stamp - state["bad_since"]) if phase == "recovered" else None}
