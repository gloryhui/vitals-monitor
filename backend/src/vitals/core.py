#!/usr/bin/env python3
"""Small, read-only Linux monitor with a bounded SQLite history archive.

1 s: /proc CPU, memory, load, uptime, network and physical disk counters.
5 s: sensors. 30 s: filesystem capacity and link information.
15 s: containers. 60 s: SMART (without waking standby disks).
5 min: Docker space accounting. 1 h: system / hardware inventory.
Samples and slow collector observations are kept for retention_days (default
90) and pruned hourly in committed batches. HTTP handlers read cached live
snapshots or query bounded history from SQLite.
"""

import ipaddress
import json
import math
import os
import re
import secrets
import socket
import sqlite3
import subprocess
import threading
import time
import zlib
from contextlib import closing
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from .auth import AuthError, AuthStore, SESSION_COOKIE
from .features import (DEFAULT_CONFIG, EventEngine, ProcessSampler, ServiceChecker,
                       UnsupportedCollector, detect_environment, load_configuration,
                       observations, require_tool)
from .store import (ROLLUP_BUCKET, ROLLUP_MIN_SPAN, SQLiteStore, TREND_KEYS,
                    decode_archive, encode_archive)

HOST = "0.0.0.0"
PORT = 8790
SAMPLE_INTERVAL = 1.0
PRUNE_INTERVAL = 3600
ROLLUP_INTERVAL = 300
DATABASE_PATH = Path(os.environ.get("VITALS_DB") or os.environ.get("SERVER_INFO_DB", "/var/lib/server-info/metrics.sqlite3"))
CONFIG_PATH = Path(os.environ.get("VITALS_CONFIG") or os.environ.get("SERVER_INFO_CONFIG",
                   Path(__file__).resolve().parents[3] / "config" / "vitals-config.json"))
ALLOWED_NETWORKS = (ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"))
_state_lock = threading.Lock()
_state = {}
_groups = {}
_store = None
_started_at = time.time()
_sampler_error = None
_storage_error = None
_event_error = None
_event_engine = None
_configuration = DEFAULT_CONFIG
_process_sampler = ProcessSampler()
_service_checker = None
_auth = None
_prune_state = {"at": None, "removed": {}, "sessions": 0}
_login_failures = {}
_login_lock = threading.Lock()
MAX_TRACKED_CLIENTS = 4096

def timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def run(cmd, timeout=10, allow_nonzero=False):
    # Never use a shell; no arguments come from HTTP requests.
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False,
                            encoding="utf-8", errors="replace",
                            env={**os.environ, "LC_ALL": "C"})
    if result.returncode and not allow_nonzero:
        raise RuntimeError(f"{cmd[0]}: {(result.stderr.strip() or 'exit ' + str(result.returncode))[:160]}")
    return result.stdout.strip()


def number(raw):
    try:
        value = float(raw)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def cpu_snapshot():
    result = {}
    for line in read_text("/proc/stat").splitlines():
        parts = line.split()
        if parts and re.fullmatch(r"cpu\d*", parts[0]) and len(parts) >= 6:
            values = list(map(int, parts[1:9]))
            result[parts[0]] = (sum(values), values[3] + values[4])
    if "cpu" not in result:
        raise RuntimeError("无法读取 CPU 计数器")
    return result


def disk_snapshot():
    result = {}
    for line in read_text("/proc/diskstats").splitlines():
        parts = line.split()
        # Exclude partitions and device-mapper devices to avoid counting I/O twice.
        if len(parts) >= 10 and re.fullmatch(r"nvme\d+n\d+|sd[a-z]+|vd[a-z]+|mmcblk\d+", parts[2]):
            result[parts[2]] = (int(parts[5]), int(parts[9]))
    return result


def default_iface():
    routes = []
    for line in read_text("/proc/net/route").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 8 and parts[1] == "00000000" and int(parts[3], 16) & 1:
            routes.append((int(parts[6]), parts[0]))
    return min(routes)[1] if routes else ""


def net_snapshot(iface):
    base = f"/sys/class/net/{iface}/statistics"
    return (number(read_text(f"{base}/rx_bytes")), number(read_text(f"{base}/tx_bytes"))) if iface else (None, None)


def rate(current, previous, elapsed):
    if current is None or previous is None or current < previous:
        return None
    return round((current - previous) / elapsed)


def memory_info():
    values = {}
    for line in read_text("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0])
    total, available = values["MemTotal"], values["MemAvailable"]
    swap_total = values.get("SwapTotal", 0)
    swap_used = max(0, swap_total - values.get("SwapFree", 0))
    return {
        "total_bytes": total * 1024, "available_bytes": available * 1024,
        "used_bytes": max(0, total - available) * 1024,
        "used_percent": round((total - available) / total * 100, 1),
        "cache_bytes": max(0, values.get("Cached", 0) + values.get("SReclaimable", 0) - values.get("Shmem", 0)) * 1024,
        "swap_total_bytes": swap_total * 1024, "swap_used_bytes": swap_used * 1024,
        "swap_percent": round(swap_used / swap_total * 100, 1) if swap_total else 0,
    }


def temperatures():
    require_tool("sensors")
    try:
        data = json.loads(run(["sensors", "-j"], timeout=3))
    except RuntimeError as exc:
        if "no sensors" in str(exc).lower():
            raise UnsupportedCollector("当前环境未提供温度传感器") from exc
        raise
    result = []
    for chip_name, chip in data.items():
        if not isinstance(chip, dict):
            continue
        for label, readings in chip.items():
            if not isinstance(readings, dict):
                continue
            for key, value in readings.items():
                if re.fullmatch(r"temp\d+_input", key) and number(value) is not None:
                    prefix = key.removesuffix("input")
                    result.append({"chip": chip_name, "label": label, "value": round(value, 1),
                                   "critical": number(readings.get(prefix + "crit"))})
    if not result:
        raise UnsupportedCollector("当前环境未提供温度传感器")
    return result


def filesystem_usage():
    output = run(["df", "-B1", "--output=source,fstype,size,used,avail,pcent,target",
                  "-x", "tmpfs", "-x", "devtmpfs", "-x", "squashfs", "-x", "efivarfs", "-x", "overlay"])
    rows = []
    for line in output.splitlines()[1:]:
        parts = line.split(None, 6)
        if len(parts) == 7 and parts[0].startswith("/dev/"):
            source, fs_type, size, used, avail, percent, mount = parts
            rows.append({"source": source, "type": fs_type, "mount": mount, "size_bytes": int(size),
                         "used_bytes": int(used), "avail_bytes": int(avail), "used_percent": int(percent.rstrip("%"))})
    return rows


def block_devices():
    data = json.loads(run(["lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE,SIZE,MODEL,TRAN,ROTA"]))
    return [item for item in data.get("blockdevices", []) if item.get("type") == "disk"]


def parse_smart(data, device):
    log = data.get("nvme_smart_health_information_log", {})
    attributes = {item["id"]: item.get("raw", {}).get("value")
                  for item in data.get("ata_smart_attributes", {}).get("table", [])}
    messages = " ".join(item.get("string", "") for item in data.get("smartctl", {}).get("messages", []))
    asleep = bool(re.search(r"STANDBY|SLEEP", messages, re.I))
    passed = data.get("smart_status", {}).get("passed")
    unsupported = passed is None and (data.get("smart_support", {}).get("available") is False or bool(re.search(
        r"SMART support.*(?:not supported|unavailable)|does not support SMART|unsupported (?:device|protocol)", messages, re.I)))
    return {
        "available": not unsupported,
        "device": device["name"], "model": data.get("model_name") or device.get("model"),
        "size_bytes": device.get("size"), "kind": "NVMe" if device.get("tran") == "nvme" else "HDD" if device.get("rota") else "SSD",
        "standby": asleep, "passed": passed,
        "error": None if passed is not None or asleep else "未能读取 SMART 健康状态",
        "temperature": log.get("temperature", data.get("temperature", {}).get("current")),
        "power_on_hours": log.get("power_on_hours", data.get("power_on_time", {}).get("hours")),
        "percentage_used": log.get("percentage_used"), "available_spare": log.get("available_spare"),
        "unsafe_shutdowns": log.get("unsafe_shutdowns"), "media_errors": log.get("media_errors"),
        "reallocated_sectors": attributes.get(5), "pending_sectors": attributes.get(197),
        "uncorrectable_sectors": attributes.get(198), "udma_crc_errors": attributes.get(199),
        "written_bytes": log["data_units_written"] * 512000 if "data_units_written" in log else None,
    }


def collect_smart():
    require_tool("smartctl")
    require_tool("lsblk")
    results = []
    for device in block_devices():
        try:
            # Nonzero SMART exit codes can report health warnings and still contain valid JSON.
            data = json.loads(run(["smartctl", "-n", "standby", "-a", "-j", device["path"]], timeout=10, allow_nonzero=True))
            results.append(parse_smart(data, device))
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
            results.append({"device": device["name"], "model": device.get("model"), "error": str(exc)[:180]})
    if results and all(item.get("available") is False for item in results):
        raise UnsupportedCollector("当前磁盘未开放 SMART 信息")
    if not results:
        raise UnsupportedCollector("当前环境没有可读取 SMART 的物理磁盘")
    return [item for item in results if item.get("available") is not False]


def collect_containers():
    require_tool("docker")
    rows = [json.loads(line) for line in run(["docker", "ps", "-a", "--format", "{{json .}}"]).splitlines() if line]
    return [{"name": row["Names"], "state": row["State"], "status": row["Status"],
             "image": row["Image"],
             "health": "unhealthy" if "(unhealthy)" in row["Status"] else "starting" if "(health: starting)" in row["Status"] else "healthy" if "(healthy)" in row["Status"] else None}
            for row in sorted(rows, key=lambda row: (row["State"] != "running", row["Names"]))]


def collect_docker_usage():
    require_tool("docker")
    return [json.loads(line) for line in run(["docker", "system", "df", "--format", "{{json .}}"], timeout=30).splitlines() if line]


def collect_network_info():
    require_tool("ip")
    iface = default_iface()
    if not iface:
        return {"interface": "", "addresses": [], "speed_mbps": None, "duplex": None}
    rows = json.loads(run(["ip", "-j", "address", "show", "dev", iface]))
    speed = number(read_text(f"/sys/class/net/{iface}/speed"))
    return {"interface": iface, "addresses": [f"{item['local']}/{item['prefixlen']}"
            for row in rows for item in row.get("addr_info", [])],
            "speed_mbps": speed if speed and speed > 0 else None,
            "duplex": read_text(f"/sys/class/net/{iface}/duplex").strip() or None}


def parse_dimms(output):
    modules = []
    for block in output.split("Memory Device")[1:]:
        fields = {}
        for line in block.splitlines():
            key, sep, value = line.strip().partition(": ")
            if sep:
                fields[key] = value.strip()
        if not re.match(r"\d+ (MB|GB|TB)$", fields.get("Size", "")):
            continue
        speed = fields.get("Configured Memory Speed") or fields.get("Speed")
        modules.append({"size": fields.get("Size"), "type": fields.get("Type"),
                        "speed": speed if speed and speed != "Unknown" else None,
                        "slot": fields.get("Bank Locator") or fields.get("Locator"),
                        "model": fields.get("Part Number")})
    return modules


def collect_system():
    os_info = {}
    for line in read_text("/etc/os-release").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            os_info[key] = value.strip('"')
    cpu_fields = {}
    for line in read_text("/proc/cpuinfo").split("\n\n")[0].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            cpu_fields[key.strip()] = value.strip()
    physical_cores = set()
    for block in read_text("/proc/cpuinfo").split("\n\n"):
        fields = dict((line.split(":", 1)[0].strip(), line.split(":", 1)[1].strip()) for line in block.splitlines() if ":" in line)
        if "core id" in fields:
            physical_cores.add((fields.get("physical id", "0"), fields["core id"]))
    memory_modules, memory_error = [], None
    try:
        memory_modules = parse_dimms(run(["dmidecode", "-t", "17"]))
        if not memory_modules:
            memory_error = "固件未提供内存条信息"
    except (OSError, RuntimeError, subprocess.SubprocessError):
        memory_error = "内存条信息不可读取"
    try:
        docker_version = run(["docker", "--version"])
    except (OSError, RuntimeError, subprocess.SubprocessError):
        docker_version = None
    return {"hostname": socket.gethostname(), "environment": detect_environment(read_text, run), "os": os_info.get("PRETTY_NAME"), "kernel": os.uname().release,
            "architecture": os.uname().machine, "timezone": read_text("/etc/timezone").strip() or time.tzname[0],
            "cpu_model": cpu_fields.get("model name") or cpu_fields.get("Hardware"),
            "cpu_threads": os.cpu_count(), "cpu_cores": len(physical_cores) or None,
            "board": " ".join(read_text(f"/sys/class/dmi/id/{key}").strip() for key in ("board_vendor", "board_name")).strip() or None,
            "memory_modules": memory_modules, "memory_error": memory_error, "docker_version": docker_version}


def collect_services():
    return _service_checker.collect() if _service_checker else []


COLLECTORS = {
    "temperatures": (5, temperatures), "filesystems": (30, filesystem_usage),
    "network_info": (30, collect_network_info), "containers": (15, collect_containers),
    "smart": (60, collect_smart), "docker_usage": (300, collect_docker_usage), "system": (3600, collect_system),
    "processes": (5, _process_sampler.collect), "services": (15, collect_services),
}


def group_snapshot(name):
    # Caller holds _state_lock. Published objects are replaced, never mutated.
    interval = COLLECTORS[name][0]
    group = dict(_groups.get(name, {"data": None, "updated_at": None, "error": None}))
    group["interval_seconds"] = interval
    group["age_seconds"] = round(time.monotonic() - group.pop("_monotonic"), 1) if "_monotonic" in group else None
    group["stale"] = group.get("available") is not False and (group["age_seconds"] is None or group["age_seconds"] > max(15, interval * 2.5) or bool(group["error"]))
    return group


def persist(method, *args):
    global _storage_error
    try:
        if _store is None:
            raise RuntimeError("历史数据库未初始化")
        getattr(_store, method)(*args)
    except Exception as exc:
        with _state_lock:
            _storage_error = str(exc)[:200]
        raise
    else:
        if method == "append_sample":
            with _state_lock:
                _storage_error = None


def collector_loop(name):
    interval, collector = COLLECTORS[name]
    while True:
        started = time.monotonic()
        try:
            data = collector()
            group = {"data": data, "updated_at": timestamp(), "attempted_at": time.time(), "_monotonic": time.monotonic(), "error": None, "available": True, "reason": None}
            persist("append_collector", name, group)
            with _state_lock:
                _groups[name] = group
        except UnsupportedCollector as exc:
            group = {"data": None, "updated_at": timestamp(), "attempted_at": time.time(), "_monotonic": time.monotonic(), "error": None, "available": False, "reason": str(exc)}
            try:
                persist("append_collector", name, group)
                with _state_lock:
                    _groups[name] = group
            except Exception as storage_exc:
                print(f"{name} capability archive: {storage_exc}", flush=True)
        except Exception as exc:
            print(f"{name}: {exc}", flush=True)
            with _state_lock:
                group = dict(_groups.get(name, {"data": None, "updated_at": None}))
                group["error"] = str(exc)[:200]
                group["attempted_at"] = time.time()
                if group.get("available") is False:
                    group["available"] = None
                _groups[name] = group
            try:
                persist("append_collector", name, {"data": None, "updated_at": None, "error": str(exc)[:200]})
            except Exception as storage_exc:
                print(f"{name} archive: {storage_exc}", flush=True)
        time.sleep(max(0.1, interval - (time.monotonic() - started)))


def sample_once(previous):
    prev_cpu, prev_disk, prev_iface, prev_net, prev_time = previous
    now = time.monotonic()
    elapsed = max(now - prev_time, 0.001)
    cur_cpu, cur_disk = cpu_snapshot(), disk_snapshot()
    iface = default_iface()
    cur_net = net_snapshot(iface)
    cpu = []
    for name, (total, idle) in cur_cpu.items():
        old_total, old_idle = prev_cpu.get(name, (total, idle))
        dt = total - old_total
        usage = max(0, min(100, (dt - (idle - old_idle)) / dt * 100)) if dt > 0 else None
        core = {"name": name, "usage_percent": round(usage, 1) if usage is not None else None}
        if name != "cpu":
            freq = number(read_text(f"/sys/devices/system/cpu/{name}/cpufreq/scaling_cur_freq"))
            core["mhz"] = round(freq / 1000) if freq else None
        cpu.append(core)
    disk_io = []
    for device, counters in cur_disk.items():
        old = prev_disk.get(device, (None, None))
        read_rate, write_rate = rate(counters[0] * 512, old[0] * 512 if old[0] is not None else None, elapsed), rate(counters[1] * 512, old[1] * 512 if old[1] is not None else None, elapsed)
        disk_io.append({"device": device, "read_bps": read_rate,
                        "write_bps": write_rate})
    old_net = prev_net if iface == prev_iface else (None, None)
    snapshot = {"generated_at": timestamp(), "sampled_at": time.time(), "sample_interval": SAMPLE_INTERVAL,
                "hostname": socket.gethostname(), "uptime_seconds": number(read_text("/proc/uptime").split()[0]),
                "load": [round(value, 2) for value in os.getloadavg()],
                "cpu": {"usage_percent": next(item["usage_percent"] for item in cpu if item["name"] == "cpu"),
                        "per_core": [item for item in cpu if item["name"] != "cpu"]},
                "memory": memory_info(), "disk_io": disk_io,
                "network": {"interface": iface, "operstate": read_text(f"/sys/class/net/{iface}/operstate").strip(),
                            "rx_bps": rate(cur_net[0], old_net[0], elapsed), "tx_bps": rate(cur_net[1], old_net[1], elapsed)}}
    return snapshot, (cur_cpu, cur_disk, iface, cur_net, now)


def temperature_history():
    """Read cached temperature groups. Caller holds _state_lock.

    Multiple devices of one kind use the highest reading in the compact chart;
    the frontend still lists each individual sensor. Missing/stale values stay null.
    """
    temp_group, smart_group = group_snapshot("temperatures"), group_snapshot("smart")
    sensors = [] if temp_group["stale"] else temp_group["data"] or []
    disks = [] if smart_group["stale"] else smart_group["data"] or []
    def highest(values):
        return max(values, default=None)
    def sensor_values(predicate):
        return [item["value"] for item in sensors if predicate(item) and number(item.get("value")) is not None]
    cpu = sensor_values(lambda t: t["label"] in ("Tctl", "Package id 0"))
    if not cpu:
        cpu = sensor_values(lambda t: bool(re.search("k10temp|coretemp|cpu", t["chip"], re.I)))
    nvme = sensor_values(lambda t: "nvme" in t["chip"].lower() and t["label"] == "Composite")
    if not nvme:
        nvme = [d["temperature"] for d in disks if d.get("kind") == "NVMe" and number(d.get("temperature")) is not None]
    return {
        "temp": highest(cpu),
        "ccd": highest(sensor_values(lambda t: t["label"].startswith("Tccd"))),
        "nvme": highest(nvme),
        "nvme_s1": highest(sensor_values(lambda t: "nvme" in t["chip"].lower() and t["label"] == "Sensor 1")),
        "nvme_s2": highest(sensor_values(lambda t: "nvme" in t["chip"].lower() and t["label"] == "Sensor 2")),
        "hdd": highest([d["temperature"] for d in disks if d.get("kind") != "NVMe" and number(d.get("temperature")) is not None]),
    }


def sampler():
    global _sampler_error
    previous = None
    while True:
        started = time.monotonic()
        try:
            if previous is None:
                iface = default_iface()
                previous = (cpu_snapshot(), disk_snapshot(), iface, net_snapshot(iface), time.monotonic())
            else:
                snapshot, previous = sample_once(previous)
                with _state_lock:
                    # Publish the same channel selection the trend archive uses,
                    # so the page never recomputes temperature aggregation.
                    channels = temperature_history()
                    snapshot["temperature_channels"] = channels
                    point = {"t": round(snapshot["sampled_at"], 3), "cpu": snapshot["cpu"]["usage_percent"],
                             "mem": snapshot["memory"]["used_percent"], **channels,
                             "rx": snapshot["network"]["rx_bps"], "tx": snapshot["network"]["tx_bps"],
                             "dr": sum(item["read_bps"] for item in snapshot["disk_io"]) if disk_io_valid(snapshot, "read_bps") else None,
                             "dw": sum(item["write_bps"] for item in snapshot["disk_io"]) if disk_io_valid(snapshot, "write_bps") else None}
                # Commit before publication. SQLite I/O never holds the live-state lock.
                persist("append_sample", snapshot, point)
                with _state_lock:
                    _state.clear()
                    _state.update(snapshot)
                    _sampler_error = None
        except Exception as exc:
            with _state_lock:
                _sampler_error = str(exc)[:200]
            print(f"sampler: {exc}", flush=True)
        time.sleep(max(0.1, SAMPLE_INTERVAL - (time.monotonic() - started)))


def disk_io_valid(snapshot, key):
    return bool(snapshot["disk_io"]) and all(item[key] is not None for item in snapshot["disk_io"])


def event_loop():
    global _event_error
    while True:
        try:
            with _state_lock:
                snapshot = dict(_state)
                groups = {name: group_snapshot(name) for name in COLLECTORS}
            _event_engine.evaluate(observations(snapshot, groups, _configuration["alerts"]))
            with _state_lock:
                _event_error = None
        except Exception as exc:
            with _state_lock:
                _event_error = str(exc)[:200]
            print(f"event journal: {exc}", flush=True)
        time.sleep(1)


def restore_groups():
    """Warm the page with the last archived observation of every collector."""
    if _store is None:
        return
    for name in COLLECTORS:
        try:
            row = _store.last_collector(name)
        except Exception as exc:
            print(f"restore {name}: {exc}", flush=True)
            continue
        if row is None:
            continue
        recorded_at, updated_at, data_json, error, metadata_json = row
        metadata = json.loads(metadata_json) if metadata_json else {}
        age = max(0.0, time.time() - (recorded_at or 0))
        with _state_lock:
            _groups[name] = {"data": decode_archive(data_json) if data_json is not None else None,
                             "updated_at": updated_at, "attempted_at": recorded_at,
                             "_monotonic": time.monotonic() - age, "error": error,
                             "available": metadata.get("available"), "reason": metadata.get("reason")}


def rollup_loop():
    """Keep the hourly rollup current and backfill after downtime."""
    while True:
        try:
            if _store is None:
                raise RuntimeError("历史数据库未初始化")
            current_hour = int(time.time() // ROLLUP_BUCKET) * ROLLUP_BUCKET
            oldest = _store.first_sample_at()
            if oldest is not None:
                oldest_hour = int(oldest // ROLLUP_BUCKET) * ROLLUP_BUCKET
                low, high = _store.rollup_bounds()
                if low is None or low > oldest_hour:
                    # First start, or an interrupted backfill: aggregate from the oldest sample.
                    start = oldest_hour
                else:
                    # Recompute the last three hours and close any gap from downtime.
                    start = max(oldest_hour, high + ROLLUP_BUCKET - 3 * ROLLUP_BUCKET)
                if start < current_hour:
                    _store.rollup(start, current_hour)
        except Exception as exc:
            print(f"rollup: {exc}", flush=True)
        time.sleep(ROLLUP_INTERVAL)


def pruner():
    """Delete archives and expired sessions outside the retention window."""
    while True:
        try:
            if _store is None:
                raise RuntimeError("历史数据库未初始化")
            cutoff = time.time() - _configuration["retention_days"] * 86400
            removed = _store.prune(cutoff)
            sessions = _auth.prune_sessions() if _auth is not None else 0
            with _state_lock:
                _prune_state.update({"at": timestamp(), "removed": removed, "sessions": sessions})
            if any(removed.values()) or sessions:
                print(f"prune: {removed} sessions={sessions}", flush=True)
        except Exception as exc:
            print(f"prune: {exc}", flush=True)
        time.sleep(PRUNE_INTERVAL)


def failure_stamps(client, window):
    """Recent failed logins for one client, dropping stale entries."""
    now = time.time()
    with _login_lock:
        stamps = [stamp for stamp in _login_failures.get(client, ()) if now - stamp < window]
        if stamps:
            _login_failures[client] = stamps
        else:
            _login_failures.pop(client, None)
        return stamps


def login_blocked(client):
    return len(failure_stamps(client, _configuration["auth"]["failure_window_seconds"])) >= _configuration["auth"]["max_failures"]


def login_retry_after(client):
    stamps = failure_stamps(client, _configuration["auth"]["failure_window_seconds"])
    if not stamps:
        return 0
    return max(1, math.ceil(min(stamps) + _configuration["auth"]["failure_window_seconds"] - time.time()))


def record_login_failure(client):
    with _login_lock:
        if len(_login_failures) >= MAX_TRACKED_CLIENTS:
            # Failed logins arrive in bursts; keep memory bounded.
            _login_failures.clear()
        _login_failures.setdefault(client, []).append(time.time())


def clear_login_failures(client):
    with _login_lock:
        _login_failures.pop(client, None)


class Handler(BaseHTTPRequestHandler):
    server_version = "vitals/1.0"
    timeout = 15

    def version_string(self):
        # Do not advertise the interpreter version.
        return self.server_version

    def client_allowed(self):
        try:
            address = ipaddress.ip_address(self.client_address[0])
            return any(address in network for network in ALLOWED_NETWORKS)
        except ValueError:
            return False

    def send_json(self, status, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def client_identity(self):
        """Throttling key: the real client behind the local reverse proxy."""
        peer = self.client_address[0]
        try:
            if not any(ipaddress.ip_address(peer) in network for network in ALLOWED_NETWORKS):
                return peer
        except ValueError:
            return peer
        forwarded = self.headers.get("X-Real-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0]
        try:
            return str(ipaddress.ip_address(forwarded.strip()))
        except ValueError:
            return peer

    def session_token(self):
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw)
        except CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def bearer_token(self):
        header = self.headers.get("Authorization")
        if not header:
            return None
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer":
            return None
        return value.strip() or None

    def current_user(self):
        if _auth is None:
            return None
        # A browser that refuses the cookie can still authenticate with the
        # token returned by /api/login; the cookie remains the safer default.
        return _auth.resolve_session(self.bearer_token() or self.session_token())

    def do_GET(self):
        if not self.client_allowed():
            self.send_json(403, {"error": "forbidden"})
            return
        url = urlsplit(self.path)
        if url.path == "/api/session":
            user = self.current_user()
            self.send_json(200, {"authenticated": user is not None, "username": user,
                                 "session_hours": _configuration["auth"]["session_hours"]})
            return
        if url.path == "/api/health":
            # Liveness stays public so external monitors need no account.
            self.health_response()
            return
        if url.path in ("/api/login", "/api/logout"):
            self.method_not_allowed()
            return
        if self.current_user() is None:
            self.send_json(401, {"error": "需要登录"})
            return
        if url.path == "/api/history":
            self.history_response(url.query)
            return
        if url.path == "/api/events":
            self.events_response(url.query)
            return
        with _state_lock:
            if url.path == "/api/status":
                age = time.time() - _state["sampled_at"] if _state else None
                healthy = age is not None and age < 5 and _sampler_error is None
                status, payload = (200 if healthy else 503), dict(_state) if healthy else {"error": _sampler_error or "采样未就绪或已过期"}
            elif url.path == "/api/overview":
                status, payload = 200, {"generated_at": timestamp(), "started_at": _started_at,
                                        "authenticated": True,
                                        "events_ok": _event_error is None,
                                        "alert_policy": dict(_configuration["alerts"]),
                                        "storage": {"ok": _store is not None and _storage_error is None, "error": _storage_error,
                                                    "retention_days": _configuration["retention_days"],
                                                    "last_prune_at": _prune_state["at"],
                                                    "last_pruned_rows": sum(_prune_state["removed"].values())},
                                        "groups": {name: group_snapshot(name) for name in COLLECTORS}}
            else:
                status, payload = 404, {"error": "not found"}
        self.send_json(status, payload)

    def health_response(self):
        with _state_lock:
            age = time.time() - _state["sampled_at"] if _state else None
            healthy = age is not None and age < 5 and _sampler_error is None
            ready = healthy and _store is not None and _storage_error is None and _event_error is None
            payload = {"ok": ready, "sample_age_seconds": age, "error": _sampler_error,
                       "storage": {"ok": _store is not None and _storage_error is None, "error": _storage_error,
                                   "retention_days": _configuration["retention_days"]}}
        self.send_json(200 if ready else 503, payload)

    def do_POST(self):
        if not self.client_allowed():
            self.send_json(403, {"error": "forbidden"})
            return
        path = urlsplit(self.path).path
        if path == "/api/login":
            self.login_response()
        elif path == "/api/logout":
            self.logout_response()
        else:
            self.method_not_allowed()

    def read_json_body(self, limit=4096):
        length = self.headers.get("Content-Length")
        if not length or not length.isdigit() or int(length) > limit:
            raise ValueError("invalid body length")
        payload = json.loads(self.rfile.read(int(length)).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid payload")
        return payload

    def login_response(self):
        if _auth is None:
            self.send_json(503, {"error": "认证服务未就绪"})
            return
        client = self.client_identity()
        if login_blocked(client):
            self.send_json(429, {"error": "尝试次数过多，请稍后再试"},
                           {"Retry-After": str(login_retry_after(client))})
            return
        try:
            body = self.read_json_body()
            username = body.get("username")
            password = body.get("password")
            if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 200:
                raise ValueError("invalid credentials")
            username = username.strip()
        except ValueError:
            self.send_json(400, {"error": "请求格式无效"})
            return
        if not _auth.authenticate(username, password):
            record_login_failure(client)
            self.send_json(401, {"error": "用户名或密码不正确"})
            return
        clear_login_failures(client)
        token = _auth.create_session(username)
        attributes = (f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; "
                      f"Max-Age={_auth.session_ttl}")
        if _configuration["auth"]["secure_cookie"]:
            attributes += "; Secure"
        self.send_json(200, {"ok": True, "username": username, "token": token,
                             "expires_in": _auth.session_ttl}, {"Set-Cookie": attributes})

    def logout_response(self):
        tokens = {token for token in (self.bearer_token(), self.session_token()) if token}
        if _auth is not None:
            for token in tokens:
                _auth.delete_session(token)
        self.send_json(200, {"ok": True},
                       {"Set-Cookie": f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"})

    def events_response(self, query):
        params = parse_qs(query)
        try:
            limit = max(1, min(100, int(params.get("limit", ["30"])[0])))
            before = int(params["before"][0]) if "before" in params else None
            if before is not None and not 0 < before <= 9223372036854775807:
                raise ValueError("invalid cursor")
        except (ValueError, TypeError):
            self.send_json(400, {"error": "invalid event query"})
            return
        try:
            if _store is None:
                raise RuntimeError("事件数据库未初始化")
            payload = _store.event_feed(limit, before)
            payload.update({"ok": _event_error is None, "generated_at": timestamp()})
            self.send_json(200, payload)
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            print(f"event query: {exc}", flush=True)
            self.send_json(503, {"error": "事件记录暂时无法读取"})

    def history_response(self, query):
        retention_seconds = _configuration["retention_days"] * 86400
        params = parse_qs(query)
        try:
            minutes = max(1, min(_configuration["retention_days"] * 1440, int(params.get("minutes", ["10"])[0])))
        except (ValueError, TypeError):
            minutes = 10
        try:
            end = float(params.get("end", [time.time()])[0])
            start = float(params.get("start", [max(0, end - minutes * 60)])[0])
            max_points = max(10, min(3600, int(params.get("max_points", ["1800"])[0])))
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end > 253402300799:
                raise ValueError("invalid range")
            # Never aggregate beyond the retention window; older rows no longer exist.
            start = max(start, end - retention_seconds)
            minutes = max(1, math.ceil((end - start) / 60))
        except (ValueError, TypeError, OverflowError):
            self.send_json(400, {"error": "invalid history range"})
            return
        try:
            if _store is None:
                raise RuntimeError("历史数据库未初始化")
            payload = _store.history(start, end, max_points)
            payload.update({"minutes": minutes, "started_at": _started_at,
                            "retention_days": _configuration["retention_days"]})
            self.send_json(200, payload)
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            print(f"history query: {exc}", flush=True)
            self.send_json(503, {"error": "历史数据暂时无法读取"})

    def method_not_allowed(self):
        if not self.client_allowed():
            self.send_json(403, {"error": "forbidden"})
        else:
            self.send_json(405, {"error": "method not allowed"}, {"Allow": "GET"})

    do_HEAD = do_GET
    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = method_not_allowed

    def send_error(self, code, message=None, explain=None):
        if code == 501 and self.command:
            self.method_not_allowed()
        else:
            super().send_error(code, message, explain)

    def log_message(self, fmt, *args):
        pass


class Server(ThreadingHTTPServer):
    # A page polls every second, so allow a short burst of queued connections.
    daemon_threads = True
    request_queue_size = 64


def bootstrap_account():
    """Preset the first account so a fresh database is never locked out."""
    settings = _configuration["auth"]
    if _auth.count_users():
        return
    username = settings["admin_user"]
    password = (os.environ.get("VITALS_ADMIN_PASSWORD") or os.environ.get("SERVER_INFO_ADMIN_PASSWORD")
                or settings["admin_password"])
    generated = password is None
    if generated:
        password = secrets.token_urlsafe(15)
    try:
        _auth.add_user(username, password)
    except AuthError as exc:
        print(f"auth: {exc}", flush=True)
        return
    if not generated:
        print(f"auth: created account {username} from configuration", flush=True)
        return
    path = Path(DATABASE_PATH).parent / "initial-admin-password"
    try:
        path.write_text(f"{username}:{password}\n", encoding="utf-8")
        path.chmod(0o600)
        print(f"auth: created account {username} with a generated password in {path}", flush=True)
    except OSError as exc:
        print(f"auth: created account {username} with password {password!r} ({path}: {exc})", flush=True)


def main():
    global _store, _configuration, _service_checker, _event_engine, _auth
    _configuration = load_configuration(CONFIG_PATH)
    _store = SQLiteStore(DATABASE_PATH)
    _auth = AuthStore(DATABASE_PATH, _configuration["auth"]["session_hours"])
    bootstrap_account()
    _service_checker = ServiceChecker(_configuration["services"], run)
    _event_engine = EventEngine(_store)
    restore_groups()
    for name in COLLECTORS:
        threading.Thread(target=collector_loop, args=(name,), daemon=True, name=name).start()
    threading.Thread(target=sampler, daemon=True, name="sampler").start()
    threading.Thread(target=event_loop, daemon=True, name="events").start()
    threading.Thread(target=rollup_loop, daemon=True, name="rollup").start()
    threading.Thread(target=pruner, daemon=True, name="pruner").start()
    server = Server((HOST, PORT), Handler)
    print(f"vitals listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
