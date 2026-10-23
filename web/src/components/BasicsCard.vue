<template>
  <section class="card">
    <div class="card-head">
      <h2>服务器基本信息 <span class="pill">{{ environmentLabel }}</span></h2>
      <span class="pill" :class="{ warn: !dash.online.value }">{{ sampledAt }}</span>
    </div>
    <div class="basics">
      <div><span>操作系统</span><strong>{{ system.os || "—" }}</strong></div>
      <div><span>处理器</span><strong>{{ cpuText }}</strong></div>
      <div><span>内存配置</span><strong>{{ memoryText }}</strong></div>
      <div><span>网络地址</span><strong>{{ networkText }}</strong></div>
      <div><span>内核 / 架构</span><strong>{{ kernelText }}</strong></div>
      <div><span>运行时间</span><strong>{{ uptimeText }}</strong></div>
      <div v-if="showBoard"><span>主板</span><strong>{{ system.board }}</strong></div>
      <div><span>时区 / 环境</span><strong>{{ environmentText }}</strong></div>
    </div>
  </section>
</template>

<script setup>
import { computed, inject } from "vue";
import { duration, fmtBytes, fmtTime } from "../format";

const dash = inject("dash");
const system = computed(() => dash.groupData("system") || {});
const network = computed(() => dash.groupData("network_info") || {});
const environment = computed(() => system.value.environment || {});
const fast = computed(() => dash.state.fast);

const environmentLabel = computed(() =>
  [environment.value.provider, environment.value.label].filter(Boolean).join(" · ") || "检测中",
);
const cpuText = computed(() => {
  const threads = system.value.cpu_threads;
  return [system.value.cpu_model, threads ? `${threads}${environment.value.kind === "vm" ? " vCPU" : " 线程"}` : null]
    .filter(Boolean)
    .join(" · ") || "—";
});
const memoryText = computed(() => {
  const modules = system.value.memory_modules || [];
  const types = [...new Set(modules.map((m) => m.type).filter(Boolean))];
  const speeds = [...new Set(modules.map((m) => m.speed).filter(Boolean))];
  return [
    fast.value ? fmtBytes(fast.value.memory.total_bytes) : null,
    ...types,
    ...speeds,
  ]
    .filter(Boolean)
    .join(" · ") || "—";
});
const networkText = computed(() => {
  const addresses = (network.value.addresses || []).filter((item) => !item.includes(":"));
  return [...addresses, network.value.interface || fast.value?.network.interface]
    .filter(Boolean)
    .join(" · ") || "—";
});
const kernelText = computed(() =>
  [system.value.kernel, system.value.architecture].filter(Boolean).join(" · ") || "—",
);
const uptimeText = computed(() => duration(fast.value?.uptime_seconds));
const showBoard = computed(
  () => !!system.value.board && !["vm", "container"].includes(environment.value.kind),
);
const environmentText = computed(
  () => [system.value.timezone, environment.value.virtualization].filter(Boolean).join(" · ") || "—",
);
const sampledAt = computed(() =>
  fast.value ? `${fmtTime(fast.value.generated_at)} 采样` : "等待采样",
);
</script>
