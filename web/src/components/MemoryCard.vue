<template>
  <article class="card">
    <div class="card-head">
      <h2>内存 <span class="pill">{{ memorySpec }}</span></h2>
      <span class="pill" :class="{ warn: processState.stale }">{{ processStatus }}</span>
    </div>
    <div class="card-body">
      <div class="metric">
        <span class="metric-value">{{ num(memory.used_percent) }}<small>%</small></span>
        <span class="muted mono" style="margin-left: 6px">{{ fmtBytes(memory.used_bytes) }} / {{ fmtBytes(memory.total_bytes) }}</span>
      </div>
      <div class="meter green">
        <i :style="{ width: `${clamp(memory.used_percent)}%` }"></i>
      </div>

      <ChartBlock
        chart-id="chartMemory"
        title="使用率趋势"
        :keys="chart.keys"
        :max="chart.max"
        :format="chart.format"
        :labels="chart.labels"
        @zoom="$emit('zoom', chart.id)"
      />

      <section>
        <div class="rank-head"><span>PID</span><span>进程</span><span>内存占比</span><span>占用内存</span></div>
        <div v-for="row in processes" :key="row.pid" class="rank-row">
          <span class="mono">{{ row.pid }}</span>
          <span class="name">{{ row.name }}</span>
          <span class="mono">{{ row.memory_percent != null ? `${row.memory_percent}%` : "采样中" }}</span>
          <span class="mono">{{ fmtBytes(row.rss_bytes) }}</span>
        </div>
        <div v-if="!processes.length" class="note">正在采样进程…</div>
      </section>

      <div class="inline-stats">
        <div>可用内存<b>{{ fmtBytes(memory.available_bytes) }}</b></div>
        <div>文件缓存<b>{{ fmtBytes(memory.cache_bytes) }}</b></div>
        <div>交换空间<b>{{ memory.swap_total_bytes ? `${fmtBytes(memory.swap_used_bytes)} / ${fmtBytes(memory.swap_total_bytes)}` : "未启用" }}</b></div>
      </div>
      <p class="note">可用内存包含可回收缓存；文件缓存可在程序需要时释放。</p>

      <details>
        <summary>内存条信息</summary>
        <div class="modules">
          <div v-for="(module, index) in modules" :key="index" class="module">
            <b>{{ module.size }} {{ module.type || "" }}</b>
            <span class="muted"> · {{ module.speed || "速率未知" }} · {{ module.slot || "" }}</span>
            <div v-if="module.model && module.model !== 'Unknown'" class="mono">{{ module.model }}</div>
          </div>
          <div v-if="!modules.length" class="module">{{ system.memory_error || "无内存条信息" }}</div>
        </div>
      </details>
    </div>
  </article>
</template>

<script setup>
import { computed, inject } from "vue";
import ChartBlock from "./ChartBlock.vue";
import { CHARTS } from "../charts";
import { fmtBytes, num } from "../format";

defineEmits(["zoom"]);

const dash = inject("dash");
const chart = CHARTS.chartMemory;
const fast = computed(() => dash.state.fast || { memory: {} });
const memory = computed(() => fast.value.memory || {});
const system = computed(() => dash.groupData("system") || {});
const modules = computed(() => system.value.memory_modules || []);
const processState = computed(() => dash.groupState("processes"));
const processStatus = computed(() => dash.groupStatus("processes"));
const processes = computed(() => processState.value.data?.memory || []);
const memorySpec = computed(() => {
  const types = [...new Set(modules.value.map((item) => item.type).filter(Boolean))];
  const speeds = [...new Set(modules.value.map((item) => item.speed).filter(Boolean))];
  return [modules.value.length ? `${modules.value.length} 条` : null, ...types, ...speeds].filter(Boolean).join(" · ") || "系统内存";
});
const clamp = (value) => (typeof value === "number" ? Math.max(0, Math.min(100, value)) : 0);
</script>
