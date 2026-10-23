<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-stats">
        <div><span>当前使用率</span><b>{{ num(cpu.usage_percent) }}%</b></div>
        <div><span>系统负载</span><b>{{ loadText }}</b></div>
        <div><span>线程</span><b>{{ cores.length }}</b></div>
        <div><span>进程数</span><b>{{ snapshot.count }}</b></div>
      </div>
    </section>

    <section class="detail-section">
      <div class="detail-section-head">
        <h3>进程排行榜</h3>
        <div class="seg">
          <button type="button" :class="{ active: sort === 'cpu' }" @click="sort = 'cpu'">按 CPU</button>
          <button type="button" :class="{ active: sort === 'memory' }" @click="sort = 'memory'">按内存</button>
        </div>
      </div>
      <table class="dtable">
        <thead>
          <tr><th>PID</th><th>进程</th><th class="num">CPU</th><th class="num">内存占比</th><th class="num">RSS</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.pid">
            <td class="mono">{{ row.pid }}</td>
            <td>{{ row.name }}</td>
            <td class="num mono">{{ row.cpu_percent != null ? `${row.cpu_percent}%` : "—" }}</td>
            <td class="num mono">{{ row.memory_percent != null ? `${row.memory_percent}%` : "—" }}</td>
            <td class="num mono">{{ fmtBytes(row.rss_bytes) }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="5" class="muted">正在读取进程…</td></tr>
        </tbody>
      </table>
      <p class="note">单核满载记为 100%，多核进程可超过 100%；排行每 5 秒刷新。</p>
    </section>

    <section class="detail-section">
      <h3>每核使用率</h3>
      <table class="dtable">
        <thead><tr><th>线程</th><th class="num">使用率</th><th class="num">频率</th></tr></thead>
        <tbody>
          <tr v-for="core in cores" :key="core.name">
            <td>{{ core.name.replace("cpu", "线程 ") }}</td>
            <td class="num mono">{{ core.usage_percent != null ? `${core.usage_percent}%` : "—" }}</td>
            <td class="num mono">{{ core.mhz ? `${core.mhz} MHz` : "—" }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "../api";
import { fmtBytes, num } from "../format";

const dash = inject("dash");
const fast = computed(() => dash.state.fast || {});
const cpu = computed(() => fast.value.cpu || { usage_percent: null, per_core: [] });
const cores = computed(() => cpu.value.per_core || []);
const loadText = computed(() => (fast.value.load || []).map((value) => num(value, 2)).join(" / "));

const sort = ref("cpu");
const snapshot = ref({ cpu: [], memory: [], count: 0 });
let timer = null;

async function load() {
  try {
    snapshot.value = await api.processes(30);
  } catch (_) {}
}

const rows = computed(() => (sort.value === "cpu" ? snapshot.value.cpu : snapshot.value.memory));

onMounted(() => {
  load();
  timer = setInterval(load, 5000);
});
onBeforeUnmount(() => clearInterval(timer));
</script>
