<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-stats">
        <div><span>已用</span><b>{{ num(memory.used_percent) }}%</b></div>
        <div><span>总量</span><b>{{ fmtBytes(memory.total_bytes) }}</b></div>
        <div><span>可用</span><b>{{ fmtBytes(memory.available_bytes) }}</b></div>
        <div><span>交换</span><b>{{ memory.swap_total_bytes ? `${fmtBytes(memory.swap_used_bytes)} / ${fmtBytes(memory.swap_total_bytes)}` : "未启用" }}</b></div>
      </div>
      <div class="meter green"><i :style="{ width: `${memory.used_percent || 0}%` }"></i></div>
    </section>

    <section class="detail-section">
      <h3>内存构成</h3>
      <table class="dtable">
        <tbody>
          <tr><td>物理内存</td><td class="num mono">{{ fmtBytes(memory.total_bytes) }}</td></tr>
          <tr><td>已使用</td><td class="num mono">{{ fmtBytes(memory.used_bytes) }}</td></tr>
          <tr><td>可用</td><td class="num mono">{{ fmtBytes(memory.available_bytes) }}</td></tr>
          <tr><td>文件缓存</td><td class="num mono">{{ fmtBytes(memory.cache_bytes) }}</td></tr>
          <tr><td>交换使用</td><td class="num mono">{{ fmtBytes(memory.swap_used_bytes) }}</td></tr>
        </tbody>
      </table>
    </section>

    <section class="detail-section">
      <div class="detail-section-head">
        <h3>进程内存排行</h3>
        <span class="muted">{{ snapshot.count }} 个进程</span>
      </div>
      <table class="dtable">
        <thead>
          <tr><th>PID</th><th>进程</th><th class="num">内存占比</th><th class="num">RSS</th><th class="num">CPU</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in snapshot.memory" :key="row.pid">
            <td class="mono">{{ row.pid }}</td>
            <td>{{ row.name }}</td>
            <td class="num mono">{{ row.memory_percent != null ? `${row.memory_percent}%` : "—" }}</td>
            <td class="num mono">{{ fmtBytes(row.rss_bytes) }}</td>
            <td class="num mono">{{ row.cpu_percent != null ? `${row.cpu_percent}%` : "—" }}</td>
          </tr>
          <tr v-if="!snapshot.memory.length"><td colspan="5" class="muted">正在读取进程…</td></tr>
        </tbody>
      </table>
    </section>

    <section class="detail-section">
      <h3>内存条</h3>
      <table class="dtable">
        <thead><tr><th>容量</th><th>类型</th><th>速率</th><th>插槽</th><th>型号</th></tr></thead>
        <tbody>
          <tr v-for="(module, index) in modules" :key="index">
            <td>{{ module.size }}</td>
            <td>{{ module.type || "—" }}</td>
            <td>{{ module.speed || "—" }}</td>
            <td>{{ module.slot || "—" }}</td>
            <td class="mono">{{ module.model || "—" }}</td>
          </tr>
          <tr v-if="!modules.length"><td colspan="5" class="muted">{{ system.memory_error || "无内存条信息" }}</td></tr>
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
const memory = computed(() => fast.value.memory || {});
const system = computed(() => dash.groupData("system") || {});
const modules = computed(() => system.value.memory_modules || []);
const snapshot = ref({ memory: [], count: 0 });
let timer = null;

async function load() {
  try {
    snapshot.value = await api.processes(30);
  } catch (_) {}
}

onMounted(() => {
  load();
  timer = setInterval(load, 5000);
});
onBeforeUnmount(() => clearInterval(timer));
</script>
