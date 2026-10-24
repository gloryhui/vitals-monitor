"""Optional hardware, service checks, process rates and incident durability."""
import copy
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from vitals import core as monitor
from vitals import features as feature


class CapabilityTest(unittest.TestCase):
    def setUp(self):
        monitor._groups.clear()

    def test_missing_sensors_are_unsupported_not_failed(self):
        with patch('vitals.features.shutil.which', return_value=None):
            with self.assertRaises(feature.UnsupportedCollector):
                monitor.temperatures()

    def test_containers_expose_ports_command_and_runtime(self):
        payload = json.dumps({"ID": "abc123def456", "Names": "web", "Image": "nginx:latest",
                              "State": "running", "Status": "Up 2 hours", "Command": "\"nginx -g\"",
                              "Ports": "0.0.0.0:80->80/tcp", "RunningFor": "2 hours ago",
                              "Networks": "bridge", "Mounts": "/a,/b", "CreatedAt": "2026-10-22"})
        with patch.object(monitor, "require_tool"), patch.object(monitor, "run", return_value=payload):
            rows = monitor.collect_containers()
        self.assertEqual(rows[0]["id"], "abc123def456")
        self.assertEqual(rows[0]["ports"], "0.0.0.0:80->80/tcp")
        self.assertEqual(rows[0]["running_for"], "2 hours ago")
        self.assertIn("nginx", rows[0]["command"])

    def test_cpu_snapshot_reports_iowait_and_steal(self):
        stat = "cpu  1 0 1 1 2 0 0 3 0 0\ncpu0 1 0 1 1 2 0 0 3 0 0\n"
        with patch.object(monitor, "read_text", return_value=stat):
            data = monitor.cpu_snapshot()
        self.assertEqual(data["cpu"], (8, 1, 2, 3))

    def test_host_health_collects_fd_zombies_tcp_and_systemd(self):
        def read(path):
            if path == "/proc/sys/fs/file-nr":
                return "100 0 1000"
            if path == "/proc/sys/fs/nr_open":
                return "1000"
            if path == "/proc/net/tcp":
                return "hdr\n a b c 01\n d e f 06\n"
            if path == "/proc/net/tcp6":
                return "hdr\n"
            if path.endswith("/stat"):
                return "1 (z) Z 1 1 1 1 0 0 0 0 0"
            if path == "/proc/vmstat":
                return "oom_kill 3\n"
            return ""

        with patch.object(monitor, "read_text", side_effect=read), \
                patch.object(monitor.os, "listdir", return_value=["1", "self"]), \
                patch.object(monitor, "run", return_value="failed.service loaded failed failed\n"):
            data = monitor.collect_host_health()
        self.assertEqual(data["fd_percent"], 10.0)
        self.assertEqual(data["zombies"], 1)
        self.assertEqual(data["systemd_failed"], 1)
        self.assertEqual(data["tcp_established"], 1)
        self.assertEqual(data["oom_kill"], 3)

    def test_temperatures_include_fans_and_voltage(self):
        payload = json.dumps({
            "coretemp-isa-0000": {
                "Package id 0": {"temp1_input": 45.0, "temp1_crit": 100.0},
                "fan1": {"fan1_input": 1200, "fan1_min": 0, "fan1_max": 3000},
                "in0": {"in0_input": 1.2, "in0_min": 0.8, "in0_max": 1.4},
            }
        })
        with patch.object(monitor, "require_tool"), patch.object(monitor, "run", return_value=payload):
            rows = monitor.temperatures()
        self.assertEqual({row["kind"] for row in rows}, {"temp", "fan", "voltage"})
        self.assertEqual(next(row for row in rows if row["kind"] == "fan")["value"], 1200)

    def test_certificate_days_reads_not_after(self):
        context = MagicMock()
        tls = MagicMock()
        tls.__enter__.return_value = tls
        tls.getpeercert.return_value = {"notAfter": "Dec 31 23:59:59 2030 GMT"}
        context.wrap_socket.return_value = tls
        sock = MagicMock()
        sock.__enter__.return_value = sock
        with patch.object(feature.socket, "create_connection", return_value=sock), \
                patch.object(feature.ssl, "_create_unverified_context", return_value=context):
            days = feature.certificate_days("example.com", 443)
        self.assertGreater(days, 365)

    def test_docker_stats_are_parsed(self):
        payload = json.dumps({"Name": "web", "CPUPerc": "1.5%", "MemUsage": "10MiB / 1GiB",
                              "MemPerc": "1%", "NetIO": "1kB / 2kB", "BlockIO": "0B / 0B", "PIDs": "3"})
        with patch.object(monitor, "require_tool"), patch.object(monitor, "run", return_value=payload):
            rows = monitor.collect_docker_stats()
        self.assertEqual(rows[0]["name"], "web")
        self.assertEqual(rows[0]["cpu_percent"], "1.5%")
        self.assertEqual(rows[0]["pids"], "3")

    def test_docker_images_mark_usage_and_dangling(self):
        images = "\n".join([
            json.dumps({"Repository": "nginx", "Tag": "latest", "ID": "abc123def456", "Size": "100MB",
                        "CreatedSince": "1 day ago", "Digest": "<none>"}),
            json.dumps({"Repository": "<none>", "Tag": "<none>", "ID": "deadbeef0000", "Size": "50MB",
                        "CreatedSince": "2 days ago", "Digest": "<none>"}),
        ])
        containers = json.dumps({"Image": "nginx:latest", "Names": "web", "State": "running", "Status": "Up"})
        with patch.object(monitor, "require_tool"), patch.object(monitor, "run", side_effect=[images, containers]):
            rows = monitor.collect_images()
        self.assertEqual(len(rows), 2)
        used = [row for row in rows if row["in_use"]]
        self.assertEqual(len(used), 1)
        self.assertEqual(used[0]["ref"], "nginx:latest")
        dangling = [row for row in rows if row["dangling"]]
        self.assertEqual(len(dangling), 1)
        self.assertEqual(dangling[0]["repository"], "<none>")

    def test_missing_docker_is_unsupported(self):
        with patch('vitals.features.shutil.which', return_value=None):
            with self.assertRaises(feature.UnsupportedCollector):
                monitor.collect_containers()
            with self.assertRaises(feature.UnsupportedCollector):
                monitor.collect_docker_usage()

    def test_empty_sensor_response_is_unsupported(self):
        with patch.object(monitor, 'run', return_value='{}'):
            with self.assertRaises(feature.UnsupportedCollector):
                monitor.temperatures()

    def test_virtual_disk_does_not_become_a_smart_failure(self):
        with patch.object(monitor, 'block_devices', return_value=[{'name':'vda','path':'/dev/vda'}]), patch.object(monitor, 'run', return_value=json.dumps({'smart_support':{'available':False}})):
            with self.assertRaises(feature.UnsupportedCollector):
                monitor.collect_smart()

    def test_unsupported_collector_is_published_without_error_or_staleness(self):
        def unsupported():
            raise feature.UnsupportedCollector('虚拟机未提供此指标')
        with patch.dict(monitor.COLLECTORS, {'temperatures':(5,unsupported)}), patch.object(monitor, 'persist'), patch.object(monitor.time, 'sleep', side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):
                monitor.collector_loop('temperatures')
        result = monitor.group_snapshot('temperatures')
        self.assertFalse(result['available'])
        self.assertFalse(result['stale'])
        self.assertIsNone(result['error'])

    def test_temporary_sensor_failure_still_raises(self):
        with patch.object(monitor, 'run', side_effect=RuntimeError('permission denied')):
            with self.assertRaises(RuntimeError):
                monitor.temperatures()

    def test_partial_smart_feature_limit_does_not_hide_a_healthy_disk(self):
        data={'smart_status':{'passed':True}, 'smartctl':{'messages':[{'string':'Self-test log not supported'}]}}
        self.assertTrue(monitor.parse_smart(data,{'name':'sda'})['available'])

    def test_previously_unsupported_metric_can_return_a_real_read_error(self):
        monitor._groups['temperatures']={'data':None,'available':False,'error':None,'updated_at':'old'}
        def fail():raise RuntimeError('permission denied')
        with patch.dict(monitor.COLLECTORS,{'temperatures':(5,fail)}), patch.object(monitor,'persist'), patch.object(monitor.time,'sleep',side_effect=InterruptedError):
            with self.assertRaises(InterruptedError):monitor.collector_loop('temperatures')
        value=monitor.group_snapshot('temperatures')
        self.assertIsNone(value['available']);self.assertTrue(value['stale']);self.assertTrue(value['error'])

    def test_cloud_environment_is_detected_without_metadata_network_access(self):
        values={'/sys/class/dmi/id/sys_vendor':'Alibaba Cloud','/sys/class/dmi/id/product_name':'Alibaba Cloud ECS'}
        result=feature.detect_environment(lambda p:values.get(p,''),lambda *a,**kw:'kvm')
        self.assertEqual(result['provider'],'阿里云')
        self.assertEqual(result['kind'],'vm')


class ProcessTest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        (self.root/'meminfo').write_text('MemTotal: 1024000 kB\n')
        self.clock=1000
        self.sampler=feature.ProcessSampler(self.root,lambda:self.clock)

    def tearDown(self):
        self.directory.cleanup()

    def write_process(self,pid,ticks,rss=100,start=10,name='worker (job)'):
        path=self.root/str(pid);path.mkdir(exist_ok=True)
        fields=['S']+['0']*22
        fields[11],fields[12],fields[19],fields[21]=str(ticks),'0',str(start),str(rss)
        (path/'stat').write_text(f'{pid} ({name}) '+' '.join(fields))

    def test_cpu_uses_delta_and_names_with_parentheses_are_parsed(self):
        self.write_process(1,100)
        self.assertIsNone(self.sampler.collect()['cpu'][0]['cpu_percent'])
        self.clock+=5
        self.write_process(1,100+self.sampler.hz*5)
        row=self.sampler.collect()['cpu'][0]
        self.assertEqual(row['cpu_percent'],100)
        self.assertEqual(row['name'],'worker (job)')
        self.assertEqual(row['rss_bytes'],100*self.sampler.page_size)

    def test_pid_reuse_has_no_fake_cpu_spike(self):
        self.write_process(1,100)
        self.sampler.collect();self.clock+=5;self.write_process(1,90000,start=99)
        self.assertIsNone(self.sampler.collect()['cpu'][0]['cpu_percent'])

    def test_rankings_have_independent_top_five_and_skip_disappeared_processes(self):
        for i in range(1,8):self.write_process(i,0,rss=i*100)
        (self.root/'999').mkdir()
        self.sampler.collect();self.clock+=5
        for i in range(1,8):self.write_process(i,(8-i)*self.sampler.hz*5,rss=i*100)
        rows=self.sampler.collect()
        self.assertEqual(len(rows['cpu']),5)
        self.assertEqual(rows['cpu'][0]['pid'],1)
        self.assertEqual(rows['memory'][0]['pid'],7)
        self.assertEqual(rows['count'],7)


class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(301 if self.path=='/redirect' else 503 if self.path=='/fail' else 200)
                if self.path=='/redirect':self.send_header('Location','http://127.0.0.1:1/not-followed')
                self.end_headers()
            def log_message(self,*args):pass
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()

    def test_http_success_failure_and_redirect_without_following(self):
        checker=feature.ServiceChecker([],lambda *a,**k:'')
        for path,status,ok in [('/ok',200,True),('/fail',503,False),('/redirect',301,True)]:
            row=checker.check({'id':'web','type':'http','url':self.url+path})
            self.assertEqual(row['http_status'],status);self.assertEqual(row['ok'],ok)

    def test_systemd_uses_active_state(self):
        checker=feature.ServiceChecker([],lambda *a,**k:'LoadState=loaded\nActiveState=active\nSubState=running')
        self.assertTrue(checker.check({'id':'ssh','type':'systemd','unit':'ssh.service'})['ok'])
        checker.run=lambda *a,**k:'LoadState=loaded\nActiveState=failed\nSubState=failed'
        self.assertFalse(checker.check({'id':'ssh','type':'systemd','unit':'ssh.service'})['ok'])

    def test_tcp_and_timeout(self):
        checker=feature.ServiceChecker([],lambda *a,**k:'')
        with socket.socket() as server:
            server.bind(('127.0.0.1',0));server.listen()
            self.assertTrue(checker.check({'id':'tcp','type':'tcp','host':'127.0.0.1','port':server.getsockname()[1]})['ok'])
        with patch('vitals.features.socket.create_connection',side_effect=TimeoutError):
            row=checker.check({'id':'tcp','type':'tcp','host':'localhost','port':80})
            self.assertFalse(row['ok']);self.assertEqual(row['detail'],'检查超时')

    def test_consecutive_failure_counter_resets_after_success(self):
        checker=feature.ServiceChecker([{'id':'web','type':'http','url':self.url+'/ok'}],lambda *a,**k:'')
        checker.check=lambda c:{'id':'web','ok':False}
        self.assertEqual(checker.collect()[0]['consecutive_failures'],1)
        self.assertEqual(checker.collect()[0]['consecutive_failures'],2)
        checker.check=lambda c:{'id':'web','ok':True}
        self.assertEqual(checker.collect()[0]['consecutive_failures'],0)

    def test_real_http_checks_drive_failure_and_recovery_events(self):
        with tempfile.TemporaryDirectory() as directory:
            store=monitor.SQLiteStore(Path(directory)/'events.sqlite3')
            engine=feature.EventEngine(store)
            checker=feature.ServiceChecker([{'id':'app','name':'应用健康','type':'http','url':self.url+'/fail'}],lambda *a,**k:'')
            base=time.time()
            try:
                for i in range(5):
                    if i==3:checker.checks[0]['url']=self.url+'/ok'
                    stamp=base+i*15
                    with patch('vitals.features.time.time',return_value=stamp):
                        group={'data':checker.collect(),'available':True,'stale':False,'error':None,'attempted_at':stamp,'interval_seconds':15}
                        engine.evaluate(feature.observations({}, {'services':group},feature.DEFAULT_CONFIG['alerts']))
                feed=store.event_feed()
                self.assertEqual([r['phase'] for r in feed['events']],['recovered','triggered'])
                self.assertEqual(feed['active'],[])
            finally:store.close()

    def test_configuration_rejects_duplicates_and_unsafe_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            for checks in [
                [{'id':'a','type':'systemd','unit':'--help'}],
                [{'id':'a','type':'http','url':'file:///etc/passwd'}],
                [{'id':'a','type':'http','url':'http://user:password@localhost/'}],
                [{'id':'a','type':'tcp','host':'localhost','port':99999}],
                [{'id':'a','type':'http','url':self.url},{'id':'a','type':'http','url':self.url}],
            ]:
                path.write_text(json.dumps({'services':checks}))
                with self.assertRaises(ValueError):feature.load_configuration(path)
            for retention in (0, -1, 3651, '90', 90.5, True):
                path.write_text(json.dumps({'services':[],'retention_days':retention}))
                with self.assertRaises(ValueError):feature.load_configuration(path)
            path.write_text(json.dumps({'services':[],'retention_days':30}))
            self.assertEqual(feature.load_configuration(path)['retention_days'],30)
            path.write_text(json.dumps({'services':[]}))
            self.assertEqual(feature.load_configuration(path)['retention_days'],90)


class EventTest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'metrics.sqlite3'
        self.store=monitor.SQLiteStore(self.path);self.engine=feature.EventEngine(self.store)

    def tearDown(self):
        self.store.close();self.directory.cleanup()

    def observe(self,stamp,bad=True,recovered=False,**kw):
        item={'key':'test','stamp':stamp,'bad':bad,'recovered':recovered,'label':'测试服务','message':'检查失败','category':'service','severity':'warning','hold':0,'count':1,'recovery_hold':0,'recovery_count':1,'interval':15}
        item.update(kw);self.engine.evaluate([item])

    def test_sustained_threshold_and_hysteresis(self):
        for t in range(1000,1060):self.observe(t,hold=60,interval=1)
        self.assertEqual(self.store.event_feed()['events'],[])
        self.observe(1060,hold=60,interval=1)
        self.assertEqual(len(self.store.event_feed()['events']),1)
        # Middle band neither triggers a new event nor confirms recovery.
        self.observe(1061,bad=False,recovered=False,interval=1)
        self.assertEqual(len(self.store.event_feed()['active']),1)
        for t in range(1062,1093):self.observe(t,bad=False,recovered=True,recovery_hold=30,interval=1)
        feed=self.store.event_feed()
        self.assertEqual([r['phase'] for r in feed['events']],['recovered','triggered'])
        self.assertEqual(feed['active'],[])

    def test_repeated_same_service_observation_does_not_increment_failure_count(self):
        for _ in range(10):self.observe(1000,count=3)
        self.assertEqual(self.store.event_feed()['events'],[])
        self.observe(1015,count=3);self.observe(1030,count=3)
        self.assertEqual(len(self.store.event_feed()['events']),1)
        self.observe(1045,count=3)
        self.assertEqual(len(self.store.event_feed()['events']),1)

    def test_restart_preserves_pending_and_active_state_without_duplicate_event(self):
        self.observe(1000,count=3);self.observe(1015,count=3)
        self.engine=feature.EventEngine(self.store);self.observe(1030,count=3)
        self.engine=feature.EventEngine(self.store);self.observe(1045,count=3)
        self.assertEqual(len(self.store.event_feed()['events']),1)
        self.assertEqual(len(self.store.event_feed()['active']),1)

    def test_missing_observations_do_not_fabricate_recovery(self):
        self.observe(1000);self.engine.evaluate([])
        self.assertEqual(len(self.store.event_feed()['active']),1)

    def test_gap_resets_pending_but_keeps_an_active_incident(self):
        self.observe(1000,count=3);self.observe(1100,count=3);self.observe(1115,count=3)
        self.assertEqual(self.store.event_feed()['events'],[])
        self.observe(1130,count=3)
        self.observe(2000,bad=False,recovered=True,recovery_count=2)
        self.assertEqual(len(self.store.event_feed()['active']),1)
        self.observe(2015,bad=False,recovered=True,recovery_count=2)
        self.assertEqual(self.store.event_feed()['active'],[])

    def test_failed_event_commit_is_retryable_and_does_not_publish_state(self):
        with patch.object(self.store,'commit_events',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):self.observe(1000)
        self.assertEqual(self.engine.states,{})
        self.observe(1000)
        self.assertEqual(len(self.store.event_feed()['events']),1)

    def test_unavailable_and_stale_metrics_are_not_healthy_observations(self):
        group={'data':None,'available':False,'error':None,'stale':False,'attempted_at':time.time(),'interval_seconds':5}
        self.assertEqual(feature.observations({}, {'temperatures':group},feature.DEFAULT_CONFIG['alerts']),[])
        group.update(available=True,stale=True,data=[{'id':'web','ok':True}])
        items=feature.observations({}, {'services':group},feature.DEFAULT_CONFIG['alerts'])
        self.assertFalse(any(item['key']=='service:web' for item in items))

    def test_stalled_collector_and_sampler_create_availability_observations(self):
        now=time.time()
        snapshot={'sampled_at':now-20}
        group={'data':[], 'available':True,'error':None,'stale':True,'attempted_at':now-100,'interval_seconds':5}
        items=feature.observations(snapshot, {'temperatures':group},feature.DEFAULT_CONFIG['alerts'])
        keys={item['key']:item for item in items}
        self.assertTrue(keys['collector:sampler']['bad'])
        self.assertTrue(keys['collector:temperatures']['bad'])

    def test_event_pagination(self):
        self.observe(1000);self.observe(1015,bad=False,recovered=True)
        first=self.store.event_feed(1);second=self.store.event_feed(1,first['next_before'])
        self.assertEqual(first['events'][0]['phase'],'recovered');self.assertEqual(second['events'][0]['phase'],'triggered')

    def test_v1_database_migration_preserves_existing_samples(self):
        path=Path(self.directory.name)/'v1.sqlite3'
        with sqlite3.connect(path) as connection:
            columns=', '.join(k+' REAL' for k in monitor.TREND_KEYS)
            connection.execute(f'CREATE TABLE samples (id INTEGER PRIMARY KEY,sampled_at REAL NOT NULL UNIQUE,snapshot_json TEXT,{columns})')
            connection.execute('CREATE TABLE collector_samples (id INTEGER PRIMARY KEY,collector TEXT NOT NULL,recorded_at REAL NOT NULL,updated_at TEXT,data_json TEXT,error TEXT)')
            connection.execute("INSERT INTO samples (sampled_at,cpu) VALUES (1000,33)")
            connection.execute('PRAGMA user_version=1')
        store=monitor.SQLiteStore(path)
        try:
            self.assertEqual(store.history(900,1100)['points'][0]['cpu'],33)
            self.assertEqual(store.connection.execute('PRAGMA user_version').fetchone()[0],4)
            self.assertEqual(store.event_feed()['events'],[])
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0],0)
        finally:store.close()


if __name__=='__main__':unittest.main()
