"""Behavior checks: collector isolation, stale caches and read-only HTTP boundaries.

Run with: PYTHONPATH=backend/src python3 -m unittest discover -s backend/tests
No root privileges or external services are needed.
"""
import json
from pathlib import Path
import re
import sys
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from vitals import core as monitor
from vitals import store as store_module


class CollectorsTest(unittest.TestCase):
    def setUp(self):
        monitor._groups.clear()

    def test_counter_reset_and_missing_values_are_unknown(self):
        self.assertIsNone(monitor.rate(1, 1000, 1))
        self.assertIsNone(monitor.rate(100, None, 1))
        self.assertEqual(monitor.rate(200, 100, 2), 50)

    def test_nonzero_smart_exit_can_still_contain_health_data(self):
        output = monitor.run([sys.executable, "-c", 'import sys; print(\'{"smart_status":{"passed":false}}\'); sys.exit(8)'], allow_nonzero=True)
        self.assertFalse(json.loads(output)["smart_status"]["passed"])

    def test_smart_standby_is_not_reported_as_healthy(self):
        value = monitor.parse_smart({"smartctl": {"messages": [{"string": "Device is in STANDBY mode, exit(2)"}]}}, {"name": "sda"})
        self.assertTrue(value["standby"])
        self.assertIsNone(value["passed"])

    def test_smart_missing_health_is_an_error_not_a_pass(self):
        value = monitor.parse_smart({}, {"name": "sda"})
        self.assertIsNone(value["passed"])
        self.assertTrue(value["error"])

    def test_memory_no_swap_and_reclaimable_cache(self):
        raw = "MemTotal: 1000 kB\nMemAvailable: 400 kB\nCached: 300 kB\nSReclaimable: 100 kB\nShmem: 50 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
        with patch.object(monitor, "read_text", return_value=raw):
            value = monitor.memory_info()
        self.assertEqual(value["used_percent"], 60)
        self.assertEqual(value["cache_bytes"], 350 * 1024)
        self.assertEqual(value["swap_percent"], 0)

    def test_sensor_voltages_are_not_temperatures(self):
        raw = json.dumps({"chip": {"voltage": {"in0_input": 1.2}, "fan": {"fan1_input": 900}, "Tctl": {"temp1_input": 52.5, "temp1_crit": 95}}})
        with patch.object(monitor, "run", return_value=raw):
            values = monitor.temperatures()
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["critical"], 95)

    def test_dimm_empty_slots_ignored_and_configured_speed_preferred(self):
        output = "Memory Device\n Size: No Module Installed\nMemory Device\n Size: 8 GB\n Type: DDR4\n Speed: 2400 MT/s\n Configured Memory Speed: 3200 MT/s\n Bank Locator: CHANNEL A\n"
        rows = monitor.parse_dimms(output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["speed"], "3200 MT/s")

    def test_group_age_uses_monotonic_time(self):
        monitor._groups["temperatures"] = {"data": [], "updated_at": "old", "_monotonic": 100, "error": None}
        with patch.object(monitor.time, "monotonic", return_value=116):
            value = monitor.group_snapshot("temperatures")
        self.assertTrue(value["stale"])
        self.assertEqual(value["age_seconds"], 16)
        self.assertNotIn("_monotonic", value)
        self.assertIn("_monotonic", monitor._groups["temperatures"])

    def test_collector_failure_keeps_old_data_but_marks_it_stale(self):
        monitor._groups["temperatures"] = {"data": [{"value": 52}], "updated_at": "old", "_monotonic": time.monotonic(), "error": None}
        with patch.dict(monitor.COLLECTORS, {"temperatures": (5, lambda: (_ for _ in ()).throw(RuntimeError("sensor failed")))}), patch.object(monitor.time, "sleep", side_effect=InterruptedError), patch.object(monitor, "persist"):

            with self.assertRaises(InterruptedError):
                monitor.collector_loop("temperatures")
        value = monitor.group_snapshot("temperatures")
        self.assertEqual(value["data"], [{"value": 52}])
        self.assertEqual(value["updated_at"], "old")
        self.assertTrue(value["stale"])
        self.assertIn("sensor failed", value["error"])

    def test_temperature_history_uses_all_sensor_channels_and_disk_cache(self):
        def group(data):
            return {"data": data, "updated_at": "now", "_monotonic": time.monotonic(), "error": None}
        monitor._groups["temperatures"] = group([
            {"chip": "k10temp", "label": "Tctl", "value": 52},
            {"chip": "k10temp", "label": "Tccd1", "value": 56},
            {"chip": "nvme-pci-0100", "label": "Composite", "value": 41},
            {"chip": "nvme-pci-0100", "label": "Sensor 1", "value": 42},
            {"chip": "nvme-pci-0100", "label": "Sensor 2", "value": 43},
        ])
        monitor._groups["smart"] = group([{"kind": "HDD", "temperature": 30}, {"kind": "NVMe", "temperature": 44}])
        with patch.object(monitor, "run", side_effect=AssertionError("temperature history must read cache only")):
            point = monitor.temperature_history()
        self.assertEqual(point, {"temp": 52, "ccd": 56, "nvme": 41, "nvme_s1": 42, "nvme_s2": 43, "hdd": 30})

    def test_stale_or_missing_temperatures_remain_null(self):
        monitor._groups["temperatures"] = {"data": [{"chip": "k10temp", "label": "Tctl", "value": 52}], "updated_at": "old", "_monotonic": time.monotonic() - 30, "error": None}
        self.assertTrue(all(v is None for v in monitor.temperature_history().values()))

    def test_temperature_history_aggregates_multiple_disks_by_maximum(self):
        monitor._groups["smart"] = {"data": [{"kind": "HDD", "temperature": 30}, {"kind": "HDD", "temperature": 38}], "updated_at": "now", "_monotonic": time.monotonic(), "error": None}
        self.assertEqual(monitor.temperature_history()["hdd"], 38)

    def test_failed_commit_does_not_publish_an_unstored_sample(self):
        old = {"sampled_at": 1, "old": True}
        monitor._state.clear()
        monitor._state.update(old)
        sample = {"sampled_at": time.time(), "cpu": {"usage_percent": 12}, "memory": {"used_percent": 30}, "network": {"rx_bps": 1, "tx_bps": 2}, "disk_io": []}
        with patch.object(monitor, "cpu_snapshot", return_value={}), patch.object(monitor, "disk_snapshot", return_value={}), patch.object(monitor, "default_iface", return_value="eth0"), patch.object(monitor, "net_snapshot", return_value=(1, 2)), patch.object(monitor, "sample_once", return_value=(sample, ())), patch.object(monitor, "temperature_history", return_value={}), patch.object(monitor, "persist", side_effect=sqlite3.OperationalError("disk full")), patch.object(monitor.time, "sleep", side_effect=[None, InterruptedError]):
            with self.assertRaises(InterruptedError):
                monitor.sampler()
        self.assertEqual(monitor._state, old)
        self.assertEqual(monitor._sampler_error, "disk full")
        monitor._sampler_error = None

    def test_fast_sampler_does_not_call_slow_collectors(self):
        previous = ({"cpu": (100, 80), "cpu0": (100, 80)}, {"sda": (100, 100)}, "old0", (5000, 5000), time.monotonic() - 1)
        def read(path):
            return {"/proc/uptime": "1000 1000", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq": "3200000", "/sys/class/net/new0/operstate": "up"}.get(path, "")
        with patch.object(monitor, "cpu_snapshot", return_value={"cpu": (200, 150), "cpu0": (200, 150)}), patch.object(monitor, "disk_snapshot", return_value={"sda": (150, 160)}), patch.object(monitor, "default_iface", return_value="new0"), patch.object(monitor, "net_snapshot", return_value=(1, 2)), patch.object(monitor, "read_text", side_effect=read), patch.object(monitor, "memory_info", return_value={}), patch.object(monitor, "run", side_effect=AssertionError("slow command on fast path")):
            snapshot, _ = monitor.sample_once(previous)
        self.assertEqual(snapshot["cpu"]["usage_percent"], 30)
        self.assertIsNone(snapshot["network"]["rx_bps"])
        self.assertIsNone(snapshot["network"]["tx_bps"])

    def test_restore_groups_warms_archived_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            store = monitor.SQLiteStore(Path(directory) / "metrics.sqlite3")
            old = time.time() - 300
            store.append_collector("temperatures", {"data": [{"value": 51}], "updated_at": "old",
                                                    "error": None, "available": True, "reason": None}, old)
            store.append_collector("containers", {"data": None, "updated_at": "old", "error": None,
                                                  "available": False, "reason": "未安装 docker"}, old)
            monitor._store = store
            try:
                monitor.restore_groups()
            finally:
                monitor._store = None
                store.close()
        temps = monitor.group_snapshot("temperatures")
        self.assertEqual(temps["data"], [{"value": 51}])
        self.assertGreater(temps["age_seconds"], 250)
        self.assertTrue(temps["stale"])
        self.assertIsNone(temps["error"])
        containers = monitor.group_snapshot("containers")
        self.assertIsNone(containers["data"])
        self.assertFalse(containers["available"])
        self.assertFalse(containers["stale"])
        self.assertEqual(containers["reason"], "未安装 docker")
        self.assertNotIn("system", monitor._groups)

    def test_sampler_publishes_temperature_channels_it_archives(self):
        sample = {"sampled_at": time.time(), "cpu": {"usage_percent": 12}, "memory": {"used_percent": 30},
                  "network": {"rx_bps": 1, "tx_bps": 2}, "disk_io": []}
        channels = {"temp": 50, "ccd": 40, "nvme": None, "nvme_s1": None, "nvme_s2": None, "hdd": None}
        monitor._state.clear()
        with patch.object(monitor, "cpu_snapshot", return_value={"cpu": (1, 1)}), \
                patch.object(monitor, "disk_snapshot", return_value={}), \
                patch.object(monitor, "default_iface", return_value=""), \
                patch.object(monitor, "net_snapshot", return_value=(None, None)), \
                patch.object(monitor, "sample_once", return_value=(sample, ())), \
                patch.object(monitor, "temperature_history", return_value=channels), \
                patch.object(monitor, "persist") as persist, \
                patch.object(monitor.time, "sleep", side_effect=[None, InterruptedError]):
            with self.assertRaises(InterruptedError):
                monitor.sampler()
        self.assertEqual(monitor._state["temperature_channels"], channels)
        self.assertEqual(persist.call_args.args[2]["temp"], 50)


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "metrics.sqlite3"
        self.store = monitor.SQLiteStore(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_reopen_preserves_old_samples_and_raw_snapshots(self):
        snapshot = {"cpu": {"per_core": [{"name": "cpu0", "mhz": 3200}]}}
        self.store.append_sample(snapshot, {"t": 1000, "cpu": 35, "nvme_s1": 43})
        self.store.append_collector("smart", {"data": [{"temperature": 31}], "updated_at": "old", "error": None}, 1000)
        self.store.close()
        self.store = monitor.SQLiteStore(self.path)
        data = self.store.history(0, time.time())
        self.assertEqual(len(data["points"]), 1)
        self.assertEqual(data["points"][0]["nvme_s1"], 43)
        row = self.store.connection.execute("SELECT snapshot_json FROM samples").fetchone()
        self.assertEqual(monitor.decode_archive(row[0]), snapshot)
        # Archived payloads are compressed BLOBs, not plain JSON text.
        self.assertIsInstance(row[0], bytes)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM collector_samples").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0], 0)

    def test_long_range_is_aggregated_without_changing_originals(self):
        for i in range(200):
            self.store.append_sample(None, {"t": 1000 + i, "cpu": i, "temp": None})
        result = self.store.history(1000, 1200, 10)
        self.assertLessEqual(len(result["points"]), 11)
        self.assertEqual(result["interval"], 20)
        self.assertEqual(result["points"][0]["cpu"], 9.5)
        self.assertIsNone(result["points"][0]["temp"])
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 200)
        self.assertEqual(len(self.store.history(1000, 1200)["points"]), 200)

    def test_duplicate_import_does_not_overwrite_original_sample(self):
        self.store.append_sample(None, {"t": 1000, "cpu": 10})
        self.store.append_sample(None, {"t": 1000, "cpu": 99})
        self.assertEqual(self.store.history(900, 1100)["points"][0]["cpu"], 10)

    def test_realistic_snapshot_is_compressed_by_more_than_half(self):
        snapshot = {"generated_at": "2026-10-22T22:00:00+08:00", "sampled_at": 1792680000.123,
                    "hostname": "ubuntu", "uptime_seconds": 43920.5, "load": [0.13, 0.12, 0.16],
                    "cpu": {"usage_percent": 6.2, "per_core": [{"name": f"cpu{i}", "usage_percent": 6.2, "mhz": 2802} for i in range(12)]},
                    "memory": {"total_bytes": 16646692864, "available_bytes": 12700000000, "used_percent": 23.2},
                    "disk_io": [{"device": "nvme0n1", "read_bps": 0, "write_bps": 4106},
                                {"device": "sda", "read_bps": 0, "write_bps": 0}],
                    "network": {"interface": "enp37s0", "operstate": "up", "rx_bps": 4300, "tx_bps": 7922}}
        raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded = monitor.encode_archive(snapshot)
        self.assertLess(len(encoded), len(raw) / 2)
        self.assertEqual(monitor.decode_archive(encoded), snapshot)

    def test_prune_deletes_rows_outside_the_retention_window(self):
        now = time.time()
        old, keep = now - 120 * 86400, now - 10 * 86400
        self.store.append_sample(None, {"t": old, "cpu": 1})
        self.store.append_sample(None, {"t": keep, "cpu": 2})
        self.store.append_collector("temperatures", {"data": [], "error": None}, old)
        self.store.append_collector("temperatures", {"data": [], "error": None}, keep)
        self.store.commit_events({}, [{"occurred_at": old, "key": "k", "phase": "triggered", "category": "c",
                                       "label": "l", "severity": "warning", "message": "m", "started_at": old,
                                       "duration_seconds": None}])
        removed = self.store.prune(now - 90 * 86400)
        self.assertEqual(removed, {"samples": 1, "collector_samples": 1, "events": 1, "samples_hourly": 0})
        self.assertEqual([row[0] for row in self.store.connection.execute("SELECT sampled_at FROM samples")], [keep])
        self.assertEqual([row[0] for row in self.store.connection.execute("SELECT recorded_at FROM collector_samples")], [keep])
        self.assertEqual(self.store.prune(now - 90 * 86400),
                         {"samples": 0, "collector_samples": 0, "events": 0, "samples_hourly": 0})

    def test_prune_commits_large_backlogs_in_batches(self):
        now = time.time()
        for i in range(7):
            self.store.append_sample(None, {"t": now - 200 * 86400 + i, "cpu": i})
        self.store.append_sample(None, {"t": now, "cpu": 99})
        with patch.object(store_module, "PRUNE_BATCH", 2):
            removed = self.store.prune(now - 100 * 86400)
        self.assertEqual(removed["samples"], 7)
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)

    def test_rollup_stores_weighted_hourly_totals(self):
        base = 1_800_000_000 - (1_800_000_000 % 3600)
        for hour in range(3):
            for offset in range(4):
                self.store.append_sample(None, {"t": base + hour * 3600 + offset * 900,
                                                "cpu": 10 + hour, "temp": 40 + hour})
        self.assertEqual(self.store.rollup(base - 3600, base + 4 * 3600), 3)
        rows = self.store.connection.execute(
            "SELECT bucket, samples, cpu_sum, cpu_n, temp_sum, temp_n FROM samples_hourly ORDER BY bucket").fetchall()
        self.assertEqual([row[0] for row in rows], [base + hour * 3600 for hour in range(3)])
        self.assertEqual([row[1] for row in rows], [4, 4, 4])
        self.assertEqual([row[2] for row in rows], [40, 44, 48])
        self.assertEqual([row[3] for row in rows], [4, 4, 4])
        self.assertEqual([row[4] for row in rows], [160, 164, 168])
        # Re-running is idempotent: totals must not double.
        self.store.rollup(base - 3600, base + 4 * 3600)
        self.assertEqual(self.store.connection.execute(
            "SELECT samples, cpu_sum FROM samples_hourly ORDER BY bucket").fetchall(), [(4, 40), (4, 44), (4, 48)])

    def test_long_range_reads_hourly_rollup_with_raw_tail(self):
        base = 1_800_000_000 - (1_800_000_000 % 3600)
        for hour in range(3):
            for offset in range(4):
                self.store.append_sample(None, {"t": base + hour * 3600 + offset * 900,
                                                "cpu": 10 + hour, "temp": 40 + hour})
        self.store.rollup(base, base + 3 * 3600)
        # A sample after the last complete hour must still show up via the raw tail.
        self.store.append_sample(None, {"t": base + 3 * 3600 + 60, "cpu": 99, "temp": 88})
        start = base - 10 * 86400
        end = base + 3 * 3600 + 600
        result = self.store.history(start, end)
        self.assertEqual(result["resolution"], "hourly")
        self.assertEqual(result["interval"], 3600)
        self.assertEqual([point["cpu"] for point in result["points"]], [10, 11, 12, 99])
        self.assertEqual([point["temp"] for point in result["points"]], [40, 41, 42, 88])
        self.assertTrue(all(point["t"] >= start for point in result["points"]))

    def test_short_range_keeps_raw_resolution(self):
        for i in range(10):
            self.store.append_sample(None, {"t": 1_800_000_000 + i, "cpu": i})
        result = self.store.history(1_800_000_000 - 60, 1_800_000_000 + 60)
        self.assertEqual(result["resolution"], "raw")
        self.assertEqual(len(result["points"]), 10)

    def test_rollup_backfill_tracks_its_bounds(self):
        base = 1_800_000_000 - (1_800_000_000 % 3600)
        for hour in range(2):
            self.store.append_sample(None, {"t": base + hour * 3600 + 5, "cpu": hour})
        self.assertIsNone(self.store.rollup_bounds()[0])
        self.assertEqual(self.store.first_sample_at(), base + 5)
        self.store.rollup(base, base + 2 * 3600)
        self.assertEqual(self.store.rollup_bounds(), (base, base + 3600))

    def test_prune_deletes_old_hourly_rollups(self):
        now = time.time()
        old_bucket = int((now - 120 * 86400) // 3600) * 3600
        keep_bucket = int((now - 10 * 86400) // 3600) * 3600
        columns = ", ".join(f"{key}_sum, {key}_n" for key in monitor.TREND_KEYS)
        for bucket in (old_bucket, keep_bucket):
            with self.store.connection:
                self.store.connection.execute(
                    f"INSERT INTO samples_hourly (bucket, samples, {columns}) VALUES (?, 1, {', '.join('0' for _ in range(24))})",
                    (bucket,))
        removed = self.store.prune(now - 90 * 86400)
        self.assertEqual(removed["samples_hourly"], 1)
        self.assertEqual([row[0] for row in self.store.connection.execute("SELECT bucket FROM samples_hourly")],
                         [keep_bucket])

    def test_missing_optional_metrics_remain_null_and_failures_are_archived(self):
        self.store.append_sample(None, {"t": 1000, "cpu": None})
        self.store.append_collector("temperatures", {"data": None, "error": "sensors unavailable"})
        self.assertIsNone(self.store.history(900, 1100)["points"][0]["temp"])
        self.assertEqual(self.store.connection.execute("SELECT error FROM collector_samples").fetchone()[0], "sensors unavailable")

    def test_wal_readers_can_query_during_writes(self):
        errors = []
        def write():
            try:
                for i in range(50):
                    self.store.append_sample(None, {"t": 1000 + i, "cpu": i})
            except Exception as error:
                errors.append(error)
        writer = threading.Thread(target=write)
        writer.start()
        while writer.is_alive():
            self.store.history(900, 1200)
        writer.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store.history(900, 1200)["points"]), 50)


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = monitor.ThreadingHTTPServer(("127.0.0.1", 0), monitor.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:" + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        monitor._state.clear()
        monitor._state.update({"sampled_at": time.time(), "cpu": {"usage_percent": 5}})
        monitor._sampler_error = None
        self.directory = tempfile.TemporaryDirectory()
        path = Path(self.directory.name) / "metrics.sqlite3"
        monitor._store = monitor.SQLiteStore(path)
        monitor._auth = monitor.AuthStore(path)
        monitor._auth.add_user("tester", "correct-horse")
        self.token = monitor._auth.create_session("tester")
        monitor._storage_error = None
        monitor._groups.clear()
        monitor._login_failures.clear()

    def tearDown(self):
        monitor._store.close()
        monitor._store = None
        monitor._auth.close()
        monitor._auth = None
        self.directory.cleanup()

    def request(self, path, method="GET", cookie=True, body=None, headers=None):
        merged = dict(headers or {})
        merged["Cookie"] = f"{monitor.SESSION_COOKIE}={self.token}" if cookie else ""
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            merged["Content-Type"] = "application/json"
        try:
            response = urlopen(Request(self.url + path, data=data, method=method, headers=merged), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read()), response.headers

    def test_get_endpoints_never_run_collectors(self):
        with patch.object(monitor, "run", side_effect=AssertionError("collector in HTTP handler")):
            for path in ("/api/status", "/api/overview", "/api/history", "/api/health", "/api/events"):
                code, _, headers = self.request(path)
                self.assertEqual(code, 200)
                self.assertEqual(headers["Cache-Control"], "no-store")

    def test_stalled_sampler_makes_health_and_status_unavailable(self):
        monitor._state["sampled_at"] = time.time() - 10
        self.assertEqual(self.request("/api/health")[0], 503)
        self.assertEqual(self.request("/api/status")[0], 503)

    def test_sampler_error_makes_health_fail_even_with_recent_snapshot(self):
        monitor._sampler_error = "read failed"
        self.assertEqual(self.request("/api/health")[0], 503)

    def test_history_window_does_not_expire_stored_samples(self):
        for age in (2000, 20):
            monitor._store.append_sample(None, {"t": time.time() - age, "cpu": 10})
        code, data, _ = self.request("/api/history?minutes=10")
        self.assertEqual(code, 200)
        self.assertEqual(len(data["points"]), 1)
        code, data, _ = self.request("/api/history?minutes=999")
        self.assertEqual(data["minutes"], 999)
        self.assertEqual(data["retention_days"], 90)
        self.assertEqual(len(data["points"]), 2)
        code, data, _ = self.request("/api/history?minutes=999999")
        self.assertEqual(code, 200)
        self.assertEqual(data["minutes"], 90 * 1440)
        self.assertLessEqual(data["end"] - data["start"], 90 * 86400)
        code, data, _ = self.request(f"/api/history?start=0&end={int(time.time())}")
        self.assertEqual(code, 200)
        self.assertLessEqual(data["end"] - data["start"], 90 * 86400)
        self.assertEqual(self.request("/api/history?minutes=bad")[1]["minutes"], 10)
        self.assertEqual(self.request("/api/history?minutes=-1")[1]["minutes"], 1)

    def test_history_accepts_absolute_range_and_rejects_nonfinite_bounds(self):
        monitor._store.append_sample(None, {"t": 1000, "cpu": 10})
        self.assertEqual(len(self.request("/api/history?start=900&end=1100")[1]["points"]), 1)
        for query in ("start=nan", "end=inf", "start=100&end=50", "start=-1", "max_points=invalid", "end=1e308"):
            self.assertEqual(self.request("/api/history?" + query)[0], 400)

    def test_database_error_returns_503_without_breaking_live_status(self):
        with patch.object(monitor._store, "history", side_effect=sqlite3.OperationalError("read failed")):
            self.assertEqual(self.request("/api/history")[0], 503)
            self.assertEqual(self.request("/api/status")[0], 200)

    def test_health_reports_failed_persistence(self):
        monitor._storage_error = "disk full"
        self.assertEqual(self.request("/api/health")[0], 503)
        self.assertFalse(self.request("/api/overview")[1]["storage"]["ok"])

    def test_write_and_unknown_methods_are_rejected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            code, _, headers = self.request("/api/status", method)
            self.assertEqual(code, 405)
            self.assertEqual(headers["Allow"], "GET")

    def test_forbidden_clients_cannot_read_or_write(self):
        with patch.object(monitor.Handler, "client_allowed", return_value=False):
            self.assertEqual(self.request("/api/status")[0], 403)
            self.assertEqual(self.request("/api/status", "POST")[0], 403)

    def test_events_are_read_only_and_validate_cursors(self):
        self.assertEqual(self.request('/api/events')[0], 200)
        for query in ('before=bad', 'before=-1', 'before=9999999999999999999999', 'limit=bad'):
            self.assertEqual(self.request('/api/events?' + query)[0], 400)
        self.assertEqual(self.request('/api/events', 'POST')[0], 405)
        with patch.object(monitor.Handler, 'client_allowed', return_value=False):
            self.assertEqual(self.request('/api/events')[0], 403)

    def test_unknown_path_is_404(self):
        self.assertEqual(self.request("/unknown")[0], 404)

    def test_protected_endpoints_require_login(self):
        for path in ("/api/status", "/api/overview", "/api/history", "/api/events"):
            self.assertEqual(self.request(path, cookie=False)[0], 401)
        self.assertEqual(self.request("/api/health", cookie=False)[0], 200)
        self.assertEqual(self.request("/api/session", cookie=False)[1]["authenticated"], False)
        self.assertEqual(self.request("/api/session")[1]["username"], "tester")

    def test_login_cookie_grants_access_and_logout_revokes_it(self):
        code, payload, headers = self.request("/api/login", "POST", cookie=False,
                                              body={"username": "tester", "password": "correct-horse"})
        self.assertEqual(code, 200)
        self.assertEqual(payload["username"], "tester")
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Path=/", cookie)
        self.token = cookie.split(";")[0].split("=", 1)[1]
        self.assertEqual(self.request("/api/status")[0], 200)
        self.assertEqual(self.request("/api/logout", "POST")[0], 200)
        self.assertEqual(self.request("/api/status")[0], 401)

    def test_bearer_token_grants_access_without_a_cookie(self):
        code, payload, _ = self.request("/api/login", "POST", cookie=False,
                                        body={"username": "tester", "password": "correct-horse"})
        token = payload["token"]
        self.assertEqual(len(token), 43)
        self.assertGreater(payload["expires_in"], 0)
        auth = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.request("/api/status", cookie=False, headers=auth)[0], 200)
        self.assertEqual(self.request("/api/session", cookie=False, headers=auth)[1]["username"], "tester")
        self.assertEqual(self.request("/api/logout", "POST", cookie=False, headers=auth)[0], 200)
        self.assertEqual(self.request("/api/status", cookie=False, headers=auth)[0], 401)

    def test_invalid_bearer_is_not_rescued_by_the_cookie(self):
        self.assertEqual(self.request("/api/status", headers={"Authorization": "Bearer bogus"})[0], 401)

    def test_login_rejects_wrong_or_malformed_credentials(self):
        code, payload, headers = self.request("/api/login", "POST", cookie=False,
                                              body={"username": "tester", "password": "wrong-password"})
        self.assertEqual(code, 401)
        self.assertNotIn("Set-Cookie", headers)
        self.assertEqual(payload["error"], "用户名或密码不正确")
        self.assertEqual(self.request("/api/login", "POST", cookie=False,
                                      body={"username": "nobody", "password": "whatever1"})[0], 401)
        for body in ({"username": 1, "password": "x"}, {"username": "tester"}, []):
            self.assertEqual(self.request("/api/login", "POST", cookie=False, body=body)[0], 400)
        self.assertEqual(self.request("/api/login", cookie=False)[0], 405)

    def test_login_is_throttled_per_client_address(self):
        for _ in range(monitor._configuration["auth"]["max_failures"]):
            self.assertEqual(self.request("/api/login", "POST", cookie=False,
                                          body={"username": "tester", "password": "nope-nope"})[0], 401)
        code, payload, headers = self.request("/api/login", "POST", cookie=False,
                                              body={"username": "tester", "password": "correct-horse"})
        self.assertEqual(code, 429)
        self.assertGreater(int(headers["Retry-After"]), 0)
        # The reverse proxy reports the real client, so another address is unaffected.
        self.assertEqual(self.request("/api/login", "POST", cookie=False,
                                      body={"username": "tester", "password": "correct-horse"},
                                      headers={"X-Real-IP": "192.0.2.44"})[0], 200)

    def test_head_has_no_body_and_hides_interpreter_version(self):
        response = urlopen(Request(self.url + "/api/health", method="HEAD"), timeout=2)
        with response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(), b"")
            self.assertNotIn("Python", response.headers["Server"])


if __name__ == "__main__":
    unittest.main()
