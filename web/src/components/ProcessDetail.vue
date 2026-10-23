<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-stats">
        <div><span>进程总数</span><b>{{ list.length }}</b></div>
        <div><span>CPU 使用率</span><b>{{ num(cpu.usage_percent) }}%</b></div>
        <div><span>内存使用率</span><b>{{ num(memory.used_percent) }}%</b></div>
        <div><span>当前筛选</span><b>{{ filtered.length }}</b></div>
      </div>
    </section>

    <section class="detail-section">
      <div class="detail-section-head">
        <h3>全部进程</h3>
        <div class="detail-toolbar">
          <input v-model="query" class="search inline" type="search" placeholder="搜索名称、命令行或路径…" />
          <div class="seg">
            <button type="button" :class="{ active: sort === 'cpu' }" @click="sort = 'cpu'">CPU</button>
            <button type="button" :class="{ active: sort === 'memory' }" @click="sort = 'memory'">内存</button>
            <button type="button" :class="{ active: sort === 'pid' }" @click="sort = 'pid'">PID</button>
            <button type="button" :class="{ active: sort === 'name' }" @click="sort = 'name'">名称</button>
          </div>
        </div>
      </div>

      <div class="phead">
        <span>PID</span><span>进程</span><span class="num">CPU</span><span class="num">内存</span>
        <span class="num">RSS</span><span>用户</span><span>命令行</span>
      </div>
      <div ref="viewport" class="vscroll" @scroll.passive="onScroll">
        <div class="vscroll-space" :style="{ height: `${filtered.length * ROW_HEIGHT}px` }">
          <div class="vscroll-rows" :style="{ transform: `translateY(${offsetY}px)` }">
            <button
              v-for="row in visibleRows"
              :key="`${row.pid}-${row.started_at}`"
              type="button"
              class="prow"
              :class="{ active: selected?.pid === row.pid }"
              @click="selected = row"
            >
              <span class="mono">{{ row.pid }}</span>
              <span class="pname">{{ row.name }}</span>
              <span class="mono num">{{ row.cpu_percent != null ? `${row.cpu_percent}%` : "—" }}</span>
              <span class="mono num">{{ row.memory_percent != null ? `${row.memory_percent}%` : "—" }}</span>
              <span class="mono num">{{ fmtBytes(row.rss_bytes) }}</span>
              <span class="puser">{{ row.user }}</span>
              <span class="pcmd" :title="row.cmdline">{{ row.cmdline || row.name }}</span>
            </button>
          </div>
          <div v-if="!filtered.length" class="pempty">正在读取进程…</div>
        </div>
      </div>
      <p class="note">显示全部 {{ list.length }} 个进程，列表虚拟滚动；排行每 5 秒刷新，单核满载记为 100%。</p>
    </section>

    <section v-if="selected" class="detail-section">
      <div class="detail-section-head">
        <h3>{{ selected.name }} · PID {{ selected.pid }}</h3>
        <span class="pill" :class="selected.state === 'Z' ? 'bad' : ''">{{ stateLabel(selected.state) }}</span>
      </div>
      <table class="dtable">
        <tbody>
          <tr><td>用户 / UID</td><td class="num mono">{{ selected.user }} ({{ selected.uid }})</td></tr>
          <tr><td>父进程</td><td class="num mono">{{ selected.ppid }}</td></tr>
          <tr><td>线程</td><td class="num mono">{{ selected.threads ?? "—" }}</td></tr>
          <tr><td>可执行文件</td><td class="num mono">{{ selected.exe || "—" }}</td></tr>
          <tr><td>工作目录</td><td class="num mono">{{ selected.cwd || "—" }}</td></tr>
          <tr><td>命令行</td><td class="num mono cmd">{{ selected.cmdline || "—" }}</td></tr>
          <tr>
            <td>内存</td>
            <td class="num mono">
              RSS {{ fmtBytes(selected.rss_bytes) }} · 虚拟 {{ fmtBytes(selected.vsize_bytes) }} ·
              Swap {{ fmtBytes(selected.swap_bytes) }}
            </td>
          </tr>
          <tr><td>CPU 时间</td><td class="num mono">{{ selected.cpu_time?.toFixed(1) }} s</td></tr>
          <tr><td>启动时间</td><td class="num mono">{{ moment(selected.started_at) }}</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "../api";
import { fmtBytes, num } from "../format";

const ROW_HEIGHT = 38;
const STATE_LABELS = {
  R: "运行",
  S: "睡眠",
  D: "磁盘等待",
  Z: "僵尸",
  T: "停止",
  t: "跟踪",
  I: "空闲",
  X: "结束",
};

const dash = inject("dash");
const fast = computed(() => dash.state.fast || {});
const cpu = computed(() => fast.value.cpu || {});
const memory = computed(() => fast.value.memory || {});

const snapshot = ref({ processes: [], count: 0, total: 0 });
const query = ref("");
const sort = ref("cpu");
const selected = ref(null);

const list = computed(() => snapshot.value.processes || []);

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase();
  const rows = needle
    ? list.value.filter(
        (row) =>
          row.name.toLowerCase().includes(needle) ||
          (row.cmdline || "").toLowerCase().includes(needle) ||
          (row.exe || "").toLowerCase().includes(needle),
      )
    : list.value;
  const sorted = [...rows];
  if (sort.value === "cpu") sorted.sort((a, b) => (b.cpu_percent ?? -1) - (a.cpu_percent ?? -1));
  else if (sort.value === "memory") sorted.sort((a, b) => (b.rss_bytes || 0) - (a.rss_bytes || 0));
  else if (sort.value === "pid") sorted.sort((a, b) => a.pid - b.pid);
  else sorted.sort((a, b) => a.name.localeCompare(b.name));
  return sorted;
});

const viewport = ref(null);
const scrollTop = ref(0);
const viewportHeight = ref(520);
const startIndex = computed(() => Math.max(0, Math.floor(scrollTop.value / ROW_HEIGHT) - 6));
const visibleCount = computed(() => Math.ceil(viewportHeight.value / ROW_HEIGHT) + 12);
const visibleRows = computed(() => filtered.value.slice(startIndex.value, startIndex.value + visibleCount.value));
const offsetY = computed(() => startIndex.value * ROW_HEIGHT);
const onScroll = (event) => {
  scrollTop.value = event.target.scrollTop;
};

const stateLabel = (state) => STATE_LABELS[state] || state || "—";
const moment = (seconds) =>
  seconds ? new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false }) : "—";

let timer = null;
let observer = null;

async function load() {
  try {
    snapshot.value = await api.processes();
  } catch (_) {}
}

watch(
  list,
  (rows) => {
    if (!rows.length) return;
    if (!selected.value) selected.value = rows[0];
    else {
      const fresh = rows.find((row) => row.pid === selected.value.pid);
      if (fresh) selected.value = fresh;
    }
  },
  { immediate: true },
);

onMounted(() => {
  load();
  timer = setInterval(load, 5000);
  observer = new ResizeObserver(() => {
    viewportHeight.value = viewport.value?.clientHeight || 520;
  });
  if (viewport.value) observer.observe(viewport.value);
});

onBeforeUnmount(() => {
  clearInterval(timer);
  observer?.disconnect();
});
</script>
