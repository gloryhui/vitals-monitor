<template>
  <article class="card">
    <div class="card-head">
      <h2>CPU <span class="pill">{{ topology }}</span></h2>
      <div class="card-tools">
        <span class="pill" :class="{ warn: processState.stale }">{{ processStatus }}</span>
        <button class="btn btn-sm" type="button" @click="$emit('detail')">详情</button>
      </div>
    </div>
    <div class="card-body">
      <div class="metric">
        <span class="metric-value">{{ num(cpu.usage_percent) }}<small>%</small></span>
      </div>
      <div class="metric-sub">{{ threadCount }} 线程 · 负载 {{ load0 }}</div>
      <div class="meter" :class="meterTone">
        <i :style="{ width: `${clamp(cpu.usage_percent)}%` }"></i>
      </div>

      <ChartBlock
        chart-id="chartUsage"
        title="使用率趋势"
        :keys="chart.keys"
        :max="chart.max"
        :format="chart.format"
        :labels="chart.labels"
        @zoom="$emit('zoom', chart.id)"
      />

      <section>
        <div class="rank-head"><span>PID</span><span>进程</span><span>CPU</span><span>占用内存</span></div>
        <div v-for="row in processes" :key="row.pid" class="rank-row">
          <span class="mono">{{ row.pid }}</span>
          <span class="name">{{ row.name }}</span>
          <span class="mono">{{ row.cpu_percent != null ? `${row.cpu_percent}%` : "采样中" }}</span>
          <span class="mono">{{ fmtBytes(row.rss_bytes) }}</span>
        </div>
        <div v-if="!processes.length" class="note">正在采样进程…</div>
        <p class="rank-note">单核满载记为 100%，多核进程可超过 100%。</p>
      </section>

      <details>
        <summary>频率与线程详情</summary>
        <div class="note">{{ system.cpu_model || "处理器信息不可用" }}</div>
        <dl class="kv">
          <dt>当前平均频率</dt><dd class="mono">{{ averageMhz }}</dd>
          <dt>系统负载</dt><dd class="mono">{{ loadText }}</dd>
          <dt>温度传感器</dt><dd>{{ sensorText }}</dd>
        </dl>
        <div class="core-grid">
          <div v-for="core in cores" :key="core.name" class="core" :title="core.mhz ? `${core.mhz} MHz` : ''">
            <div><span>{{ core.name.replace("cpu", "线程 ") }}</span><b>{{ core.usage_percent != null ? Math.round(core.usage_percent) : "—" }}%</b></div>
            <div class="meter" :class="meterTone"><i :style="{ width: `${clamp(core.usage_percent)}%` }"></i></div>
          </div>
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

defineEmits(["zoom", "detail"]);

const dash = inject("dash");
const chart = CHARTS.chartUsage;
const fast = computed(() => dash.state.fast || { cpu: { usage_percent: 0, per_core: [] }, load: [0, 0, 0] });
const cpu = computed(() => fast.value.cpu || { usage_percent: null, per_core: [] });
const cores = computed(() => cpu.value.per_core || []);
const system = computed(() => dash.groupData("system") || {});
const processState = computed(() => dash.groupState("processes"));
const processStatus = computed(() => dash.groupStatus("processes"));
const processes = computed(() => processState.value.data?.cpu || []);
const topology = computed(() => {
  const cores = system.value.cpu_cores;
  const threads = system.value.cpu_threads;
  return [cores ? `${cores} 核` : null, threads ? `${threads} 线程` : null].filter(Boolean).join(" / ") || "—";
});
const threadCount = computed(() => cores.value.length || system.value.cpu_threads || "—");
const load0 = computed(() => num(fast.value.load?.[0], 2));
const loadText = computed(() => `${(fast.value.load || []).map((value) => num(value, 2)).join(" / ")}（1 / 5 / 15 分钟）`);
const averageMhz = computed(() => {
  const values = cores.value.map((core) => core.mhz).filter((value) => typeof value === "number");
  return values.length ? `${Math.round(values.reduce((sum, value) => sum + value, 0) / values.length)} MHz` : "—";
});
const sensorText = computed(() => {
  const sensors = dash.groupData("temperatures") || [];
  const rows = sensors
    .filter((item) => /k10temp|coretemp|cpu/i.test(item.chip) || ["Tctl", "Package id 0"].includes(item.label))
    .map((item) => `${item.label} ${num(item.value)} °C`);
  return rows.join(" · ") || "—";
});
const limit = computed(() => dash.state.alertPolicy.cpu_percent || 90);
const meterTone = computed(() => {
  const value = cpu.value.usage_percent;
  if (value == null) return "";
  if (value >= limit.value) return "danger";
  if (value >= limit.value - 10) return "warning";
  return "";
});
const clamp = (value) => (typeof value === "number" ? Math.max(0, Math.min(100, value)) : 0);
</script>
