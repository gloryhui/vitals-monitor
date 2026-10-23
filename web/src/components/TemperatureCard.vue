<template>
  <article class="card full">
    <div class="card-head">
      <h2>温度监测 <span class="pill">{{ readings.length ? `${readings.length} 项温度` : "读取中" }}</span></h2>
      <span class="pill" :class="{ warn: state.stale }">{{ statusText }}</span>
    </div>
    <div class="card-body">
      <div class="temperature-grid">
        <article v-for="(item, index) in readings" :key="index" class="temperature-card" :class="{ 'stale-data': groupStale(item.group) }">
          <h3>{{ item.title }}</h3>
          <div class="temperature-reading" :class="{ bad: item.critical != null && item.value >= item.critical }">
            {{ num(item.value) }}<small>°C</small>
          </div>
          <div class="temperature-source">{{ item.note || item.source }}</div>
          <div class="group-status muted">{{ groupStatus(item.group) }}</div>
        </article>
        <div v-if="!readings.length" class="note">正在读取温度…</div>
      </div>
      <p class="note">
        传感器每 5 秒更新，SMART 磁盘温度每分钟更新。趋势图取同类设备的最高温度；30 天及以上的范围按小时聚合，保留 3 个月。
      </p>
      <ChartBlock
        chart-id="chartTemp"
        title="温度"
        :keys="chart.keys"
        :max="chart.max"
        :format="chart.format"
        :labels="chart.labels"
        tall
        @zoom="$emit('zoom', chart.id)"
      />
    </div>
  </article>
</template>

<script setup>
import { computed, inject } from "vue";
import ChartBlock from "./ChartBlock.vue";
import { CHARTS } from "../charts";
import { num } from "../format";

defineEmits(["zoom"]);

const dash = inject("dash");
const chart = CHARTS.chartTemp;
const state = computed(() => dash.groupState("temperatures"));
const statusText = computed(() => dash.groupStatus("temperatures"));

const sensors = computed(() => dash.groupData("temperatures") || []);
const disks = computed(() => dash.groupData("smart") || []);

function sensorTitle(item) {
  if (item.label === "Tctl") return "CPU 控制温度";
  if (item.label === "Tdie") return "CPU 芯片温度";
  if (item.label.startsWith("Tccd")) return `CPU 核心区域 ${item.label.replace("Tccd", "CCD ")}`;
  if (item.label.startsWith("Package id")) return "CPU 封装温度";
  if (/nvme/i.test(item.chip)) {
    return item.label === "Composite" ? "NVMe 综合温度" : item.label.replace("Sensor ", "NVMe 探头 ");
  }
  return item.label;
}

const readings = computed(() => {
  const list = sensors.value.map((item) => {
    const cpu = /k10temp|coretemp|cpu/i.test(item.chip);
    return {
      title: sensorTitle(item),
      source: cpu ? `CPU · ${item.label}` : `${item.chip} · ${item.label}`,
      value: item.value,
      critical: item.critical,
      group: "temperatures",
      order: cpu ? 0 : 1,
    };
  });
  const hasNvmeSensors = sensors.value.some(
    (item) => /nvme/i.test(item.chip) && item.label === "Composite",
  );
  for (const disk of disks.value) {
    if (disk.kind === "NVMe" && hasNvmeSensors) continue;
    list.push({
      title:
        disk.kind === "NVMe" ? "NVMe 温度" : disk.kind === "HDD" ? "机械硬盘温度" : "固态硬盘温度",
      source: `${disk.model || disk.device} · SMART`,
      value: disk.temperature,
      group: "smart",
      order: 2,
      note: disk.standby ? "磁盘休眠中，未唤醒读取" : disk.error ? "本轮读取失败" : null,
    });
  }
  return list.sort((a, b) => a.order - b.order);
});

const groupStale = (group) => dash.groupState(group).stale;
const groupStatus = (group) => dash.groupStatus(group);
</script>
