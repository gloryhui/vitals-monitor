<template>
  <div class="resource-toolbar">
    <div>
      <h2>资源状态</h2>
      <p>{{ hint }}</p>
    </div>
    <label class="muted" style="font-size: 12px">
      全局范围
      <select class="select" :value="dash.state.globalRange" @change="dash.setGlobalRange($event.target.value)">
        <option v-for="value in RANGE_OPTIONS" :key="value" :value="value">
          {{ rangeLabel(value) }}
        </option>
      </select>
    </label>
  </div>
  <div class="resource-grid">
    <CpuCard @zoom="$emit('zoom', $event)" @detail="$emit('detail', 'cpu')" />
    <MemoryCard @zoom="$emit('zoom', $event)" @detail="$emit('detail', 'memory')" />
    <TemperatureCard @zoom="$emit('zoom', $event)" @detail="$emit('detail', 'temperature')" />
    <StorageCard @zoom="$emit('zoom', $event)" @detail="$emit('detail', 'storage')" />
    <NetworkCard @zoom="$emit('zoom', $event)" @detail="$emit('detail', 'network')" />
    <ContainersCard @detail="$emit('detail', 'containers')" />
  </div>
</template>

<script setup>
import { computed, inject } from "vue";
import { RANGE_OPTIONS, rangeLabel } from "../format";
import CpuCard from "./CpuCard.vue";
import MemoryCard from "./MemoryCard.vue";
import TemperatureCard from "./TemperatureCard.vue";
import StorageCard from "./StorageCard.vue";
import NetworkCard from "./NetworkCard.vue";
import ContainersCard from "./ContainersCard.vue";

defineEmits(["zoom", "detail"]);

const dash = inject("dash");
const hint = computed(() => {
  const first = dash.state.firstSampleAt;
  const start = first
    ? new Date(first * 1000).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      })
    : null;
  const hourly = Object.values(dash.state.history).some((item) => item.resolution === "hourly");
  return [
    start ? `保留 ${dash.state.retentionDays} 天 · 始于 ${start}` : `每秒采样 · 保留 ${dash.state.retentionDays} 天`,
    hourly ? "长范围小时聚合" : null,
    "每个图表可单独选择范围",
  ]
    .filter(Boolean)
    .join(" · ");
});
</script>
