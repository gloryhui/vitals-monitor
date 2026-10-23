import { computed, reactive } from "vue";
import { api, authHeaders, setToken } from "./api";
import { finite, fmtTime } from "./format";

const CHART_IDS = ["chartUsage", "chartMemory", "chartTemp", "chartDisk", "chartNetwork"];
const THEME_KEY = "vitals-theme";
const REFRESH_KEY = "vitals-refresh";

function readStorage(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch (_) {
    return fallback;
  }
}

function writeStorage(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch (_) {}
}

export function createDashboard() {
  const state = reactive({
    ready: false,
    authenticated: false,
    username: "",
    loginMessage: "",
    theme: readStorage(THEME_KEY, "light"),
    refreshMs: Number(readStorage(REFRESH_KEY, 1000)) || 1000,
    now: performance.now(),
    fast: null,
    fastAt: 0,
    fastError: false,
    groups: {},
    overviewAt: 0,
    overviewError: false,
    storageError: false,
    retentionDays: 90,
    sessionHours: 12,
    alertPolicy: {},
    startedAt: null,
    serverOffset: 0,
    events: [],
    active: [],
    eventCursor: null,
    eventError: false,
    eventAt: 0,
    eventGeneratedAt: null,
    globalRange: 10,
    chartRanges: Object.fromEntries(CHART_IDS.map((id) => [id, 10])),
    history: {},
    live: [],
    firstSampleAt: null,
    olderLoaded: false,
    loadingOlder: false,
  });

  const eventMap = new Map();
  let pollers = [];

  function tick() {
    state.now = performance.now();
  }

  /* ---------- pollers ---------- */
  function createPoller(task, interval) {
    let timer = null;
    let running = false;
    let again = false;
    let paused = false;
    const period = typeof interval === "function" ? interval : () => interval;

    async function trigger() {
      clearTimeout(timer);
      if (paused || document.hidden) return;
      if (running) {
        again = true;
        return;
      }
      running = true;
      try {
        await task();
      } catch (error) {
        if (error.status === 401) {
          requireLogin("登录已过期，请重新登录。");
          return;
        }
        console.error("vitals refresh failed", error);
      } finally {
        running = false;
        if (paused || document.hidden) return;
        if (again) {
          again = false;
          trigger();
        } else {
          timer = setTimeout(trigger, period());
        }
      }
    }

    return {
      trigger,
      pause() {
        paused = true;
        clearTimeout(timer);
        again = false;
      },
      start() {
        paused = false;
        trigger();
      },
    };
  }

  /* ---------- data refresh ---------- */
  function pushLive(payload) {
    const disk = payload.disk_io || [];
    const complete = (key) => disk.length > 0 && disk.every((item) => finite(item[key]));
    const point = {
      t: payload.sampled_at,
      cpu: payload.cpu?.usage_percent,
      mem: payload.memory?.used_percent,
      ...(payload.temperature_channels || {}),
      rx: payload.network?.rx_bps,
      tx: payload.network?.tx_bps,
      dr: complete("read_bps") ? disk.reduce((sum, item) => sum + item.read_bps, 0) : null,
      dw: complete("write_bps") ? disk.reduce((sum, item) => sum + item.write_bps, 0) : null,
    };
    const nowSeconds = (Date.now() + state.serverOffset) / 1000;
    state.live = [...state.live.filter((item) => item.t >= nowSeconds - 120), point].slice(-150);
  }

  async function refreshFast() {
    const payload = await api.status();
    state.fast = payload;
    state.fastAt = performance.now();
    state.fastError = false;
    state.serverOffset = payload.sampled_at * 1000 - Date.now();
    pushLive(payload);
  }

  async function refreshOverview() {
    const payload = await api.overview();
    state.overviewAt = performance.now();
    state.overviewError = false;
    state.storageError = payload.storage?.ok === false;
    state.retentionDays = payload.storage?.retention_days ?? state.retentionDays;
    state.alertPolicy = payload.alert_policy || {};
    if (state.startedAt !== null && payload.started_at !== state.startedAt) {
      state.history = {};
      state.live = [];
    }
    state.startedAt = payload.started_at;
    state.groups = payload.groups || {};
  }

  async function refreshHistory() {
    const ranges = [...new Set(Object.values(state.chartRanges))];
    const results = await Promise.all(
      ranges.map(async (minutes) => [minutes, await api.history(minutes)]),
    );
    const next = {};
    let first = null;
    for (const [minutes, payload] of results) {
      next[minutes] = {
        points: payload.points || [],
        interval: payload.interval || 1,
        resolution: payload.resolution,
      };
      if (first === null) first = payload.first_sample_at;
      if (payload.points?.length && !state.fast) {
        state.serverOffset = payload.points[payload.points.length - 1].t * 1000 - Date.now();
      }
    }
    state.history = next;
    if (first !== null) state.firstSampleAt = first;
  }

  function mergeEvents(payload, older) {
    for (const row of payload.events || []) eventMap.set(row.id, row);
    state.events = [...eventMap.values()].sort((a, b) => b.id - a.id);
    state.active = payload.active || [];
    if (older || !state.olderLoaded) state.eventCursor = payload.next_before;
    state.eventAt = performance.now();
    state.eventGeneratedAt = payload.generated_at || null;
    state.eventError = false;
  }

  async function refreshEvents() {
    mergeEvents(await api.events(30), false);
  }

  const fastPoller = createPoller(refreshFast, () => state.refreshMs);
  const overviewPoller = createPoller(async () => {
    await refreshOverview();
    if (!state.fast) await refreshFast().catch(() => {});
  }, 5000);
  const historyPoller = createPoller(refreshHistory, 30000);
  const eventsPoller = createPoller(refreshEvents, 5000);
  pollers = [fastPoller, overviewPoller, historyPoller, eventsPoller];

  /* ---------- lifecycle ---------- */
  function startPollers() {
    for (const poller of pollers) poller.start();
  }

  function pausePollers() {
    for (const poller of pollers) poller.pause();
  }

  function clearData() {
    state.fast = null;
    state.fastError = false;
    state.groups = {};
    state.history = {};
    state.live = [];
    state.events = [];
    state.active = [];
    eventMap.clear();
    state.eventCursor = null;
    state.olderLoaded = false;
    state.startedAt = null;
  }

  function requireLogin(message) {
    if (!state.authenticated && state.loginMessage) return;
    pausePollers();
    state.authenticated = false;
    state.username = "";
    state.loginMessage = message || "";
    setToken(null);
    clearData();
  }

  async function login(username, password) {
    const payload = await api.login(username.trim(), password);
    setToken(payload.token);
    state.username = payload.username || username.trim();
    state.authenticated = true;
    state.loginMessage = "";
    state.sessionHours = payload.expires_in ? Math.round(payload.expires_in / 3600) : state.sessionHours;
    state.ready = true;
    startPollers();
  }

  async function logout() {
    try {
      await fetch("/api/logout", { method: "POST", headers: authHeaders() });
    } catch (_) {}
    setToken(null);
    state.authenticated = false;
    state.username = "";
    state.loginMessage = "已退出登录。";
    state.ready = true;
    pausePollers();
    clearData();
  }

  async function bootstrap() {
    try {
      const session = await api.session();
      state.sessionHours = session.session_hours ?? 12;
      if (session.authenticated) {
        state.username = session.username || "";
        state.authenticated = true;
        startPollers();
      }
    } catch (error) {
      state.loginMessage = "无法连接后端服务，请稍后刷新页面。";
    } finally {
      state.ready = true;
    }
  }

  /* ---------- view helpers ---------- */
  const online = computed(
    () =>
      !!state.fast &&
      !state.fastError &&
      state.now - state.fastAt < Math.max(state.refreshMs * 2.5, 5000),
  );

  function groupState(name) {
    const group = state.groups[name];
    if (!group) {
      return { data: null, stale: true, error: null, available: null, interval_seconds: 15, age: null };
    }
    const age = finite(group.age_seconds)
      ? group.age_seconds + (state.now - state.overviewAt) / 1000
      : null;
    const stale =
      state.overviewError ||
      group.stale ||
      age === null ||
      age > Math.max(15, group.interval_seconds * 2.5);
    return { ...group, age, stale };
  }

  function groupData(name) {
    return groupState(name).data;
  }

  function groupStatus(name) {
    const group = groupState(name);
    const interval = group.interval_seconds;
    const cycle =
      interval >= 3600
        ? "每小时"
        : interval >= 60
          ? `每 ${interval / 60} 分钟`
          : `每 ${interval || "—"} 秒`;
    if (group.available === false) return "当前环境不提供";
    if (!group.data) return group.error || state.overviewError ? "读取失败" : "读取中…";
    if (group.stale) return `数据已过期${group.updated_at ? ` · ${fmtTime(group.updated_at)}` : ""}`;
    return `${cycle} · ${fmtTime(group.updated_at)} 更新`;
  }

  const alerts = computed(() => {
    const list = [];
    if (state.storageError) list.push({ tone: "bad", text: "历史数据写入失败。" });
    if (state.eventError || (state.eventAt && state.now - state.eventAt > 15000)) {
      list.push({ tone: "warn", text: "事件记录暂时无法更新，正在重试。" });
    }
    for (const active of state.active) {
      const unconfirmed =
        finite(active.last_seen) &&
        (Date.now() + state.serverOffset) / 1000 - active.last_seen >
          Math.max(15, (active.interval || 1) * 2.5);
      list.push({
        tone: active.good_count ? "warn" : active.severity === "critical" ? "bad" : "warn",
        text: unconfirmed
          ? `${active.label} 最近一次异常尚未确认恢复，最后观察于 ${fmtTime(active.last_seen * 1000)}。`
          : active.good_count
            ? `${active.label} 正在恢复，等待连续正常确认。`
            : active.message,
      });
    }
    for (const [name, label] of [
      ["temperatures", "温度"],
      ["filesystems", "分区容量"],
      ["smart", "磁盘健康"],
      ["containers", "容器"],
      ["docker_usage", "Docker 空间"],
      ["system", "系统信息"],
      ["network_info", "网络信息"],
      ["processes", "进程排行"],
      ["services", "服务检查"],
    ]) {
      const group = groupState(name);
      if (group.available === false) continue;
      if (group.stale && (group.error || group.data || state.overviewError)) {
        list.push({ tone: "warn", text: `${label}数据${group.data ? "已过期" : "暂不可用"}。` });
      }
    }
    if (!online.value && state.fast) {
      list.unshift({ tone: "warn", text: "实时采样已中断，当前数值仅供参考。" });
    }
    return list;
  });

  const allReady = computed(() => {
    if (!online.value || !state.eventAt) return false;
    const groups = Object.values(state.groups);
    return groups.length > 0 && groups.every((g) => g.available === false || g.data !== null);
  });

  const temperatureKeys = computed(() => {
    const sensors = groupData("temperatures") || [];
    const disks = groupData("smart") || [];
    const keys = new Set();
    if (
      sensors.some(
        (t) => /cpu|k10temp|coretemp/i.test(t.chip) || t.label === "Package id 0",
      )
    )
      keys.add("temp");
    if (sensors.some((t) => t.label.startsWith("Tccd"))) keys.add("ccd");
    if (
      sensors.some((t) => /nvme/i.test(t.chip) && t.label === "Composite") ||
      disks.some((d) => d.kind === "NVMe" && finite(d.temperature))
    )
      keys.add("nvme");
    if (sensors.some((t) => /nvme/i.test(t.chip) && t.label === "Sensor 1")) keys.add("nvme_s1");
    if (sensors.some((t) => /nvme/i.test(t.chip) && t.label === "Sensor 2")) keys.add("nvme_s2");
    if (disks.some((d) => d.kind !== "NVMe" && finite(d.temperature))) keys.add("hdd");
    return keys;
  });

  function chartPoints(chartId) {
    const range = state.chartRanges[chartId] || state.globalRange;
    const stored = state.history[range];
    const nowSeconds = (Date.now() + state.serverOffset) / 1000;
    const cutoff = nowSeconds - range * 60;
    const map = new Map();
    for (const point of stored?.points || []) {
      if (point.t >= cutoff) map.set(Math.round(point.t * 1000), point);
    }
    const lastStored = stored?.points?.length ? stored.points[stored.points.length - 1].t : cutoff;
    for (const point of state.live) {
      if (point.t > lastStored) map.set(Math.round(point.t * 1000), point);
    }
    return [...map.values()].sort((a, b) => a.t - b.t);
  }

  function chartInterval(chartId) {
    const range = state.chartRanges[chartId] || state.globalRange;
    return state.history[range]?.interval || 1;
  }

  function setChartRange(chartId, minutes) {
    state.chartRanges[chartId] = Number(minutes);
    historyPoller.trigger();
  }

  function setGlobalRange(minutes) {
    const value = Number(minutes);
    state.globalRange = value;
    for (const id of CHART_IDS) state.chartRanges[id] = value;
    historyPoller.trigger();
  }

  function setRefreshMs(value) {
    state.refreshMs = Number(value);
    writeStorage(REFRESH_KEY, state.refreshMs);
    fastPoller.trigger();
  }

  function toggleTheme() {
    state.theme = state.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = state.theme;
    writeStorage(THEME_KEY, state.theme);
  }

  function refreshAll() {
    fastPoller.trigger();
    overviewPoller.trigger();
    historyPoller.trigger();
    eventsPoller.trigger();
  }

  async function loadOlderEvents() {
    if (state.eventCursor === null || state.loadingOlder) return;
    state.loadingOlder = true;
    try {
      mergeEvents(await api.events(30, state.eventCursor), true);
      state.olderLoaded = true;
    } catch (error) {
      if (error.status === 401) requireLogin("登录已过期，请重新登录。");
      else state.eventError = true;
    } finally {
      state.loadingOlder = false;
    }
  }

  return {
    state,
    alerts,
    allReady,
    temperatureKeys,
    online,
    groupState,
    groupData,
    groupStatus,
    chartPoints,
    chartInterval,
    setChartRange,
    setGlobalRange,
    setRefreshMs,
    toggleTheme,
    refreshAll,
    loadOlderEvents,
    login,
    logout,
    bootstrap,
    startPollers,
    pausePollers,
    requireLogin,
    tick,
  };
}
