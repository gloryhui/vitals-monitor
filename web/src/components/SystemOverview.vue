<template>
  <section class="card overview-card">
    <div class="card-head">
      <h2>系统概览</h2>
      <div class="card-tools">
        <span class="pill">{{ environmentLabel }}</span>
        <span class="pill">{{ sampledAt }} 采样</span>
      </div>
    </div>

    <div class="overview-row">
      <div class="row-head">
        <span class="row-kicker">基本信息</span>
      </div>
      <div class="basics-grid">
        <div class="fact major"><span>操作系统</span><strong>{{ system.os || "—" }}</strong></div>
        <div class="fact major"><span>处理器 · {{ system.cpu_threads }} 线程</span><strong>{{ cpuShort }}</strong></div>
        <div class="fact major"><span>内存配置</span><strong>{{ memoryText }}</strong></div>
        <div class="fact major"><span>运行时间</span><strong>{{ uptimeText }}</strong></div>
        <div class="fact minor"><span>网络地址</span><strong>{{ networkText }}</strong></div>
        <div class="fact minor"><span>内核 / 架构</span><strong>{{ kernelText }}</strong></div>
        <div class="fact minor"><span>主板</span><strong :title="system.board">{{ system.board || "—" }}</strong></div>
        <div class="fact minor"><span>时区 / 环境</span><strong>{{ environmentText }}</strong></div>
      </div>
    </div>

    <div class="overview-row">
      <div class="row-head">
        <span class="row-kicker">服务检查</span>
        <div class="col-tools">
          <span class="pill" :class="serviceTone">{{ serviceSummary }}</span>
          <button class="btn btn-sm" type="button" @click="$emit('detail')">详情</button>
        </div>
      </div>
      <div class="service-row">
        <div v-for="item in services" :key="item.id" class="service-chip" :class="{ bad: !item.ok }">
          <div class="service-chip-top">
            <i></i>
            <span class="name">{{ item.name }}</span>
          </div>
          <div class="service-chip-meta">
            <span>{{ item.ok ? item.detail : "检查失败" }}</span>
            <b>{{ item.latency_ms }} ms</b>
          </div>
        </div>
        <div v-if="!services.length" class="note">暂无服务检查配置</div>
      </div>
    </div>

    <div class="overview-row">
      <div class="row-head">
        <span class="row-kicker">系统健康</span>
      </div>
      <div class="health-row">
        <div class="health-main">
          <span>文件描述符</span>
          <strong>{{ health.fd_used ?? "—" }}<small> / {{ health.fd_max ?? "—" }}</small></strong>
          <div class="meter" :class="fdTone"><i :style="{ width: `${health.fd_percent || 0}%` }"></i></div>
          <em>已使用 {{ health.fd_percent ?? "—" }}%</em>
        </div>
        <div class="fact"><span>僵尸进程</span><strong :class="{ bad: health.zombies > 0 }">{{ health.zombies ?? "—" }}</strong></div>
        <div class="fact"><span>systemd 失败</span><strong :class="{ bad: health.systemd_failed > 0 }">{{ health.systemd_failed ?? "—" }}</strong></div>
        <div class="fact"><span>TCP 已建立</span><strong>{{ health.tcp_established ?? "—" }}</strong></div>
        <div class="fact"><span>OOM 次数</span><strong :class="{ bad: health.oom_kill > 0 }">{{ health.oom_kill ?? "—" }}</strong></div>
        <div class="fact"><span>CPU iowait</span><strong>{{ iowaitText }}</strong></div>
        <div class="fact"><span>CPU steal</span><strong>{{ stealText }}</strong></div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, inject } from "vue";
import { duration, fmtBytes, fmtTime, num } from "../format";

defineEmits(["detail"]);

const dash = inject("dash");
const system = computed(() => dash.groupData("system") || {});
const network = computed(() => dash.groupData("network_info") || {});
const environment = computed(() => system.value.environment || {});
const services = computed(() => dash.groupData("services") || []);
const health = computed(() => dash.groupData("host_health") || {});
const fast = computed(() => dash.state.fast);

const environmentLabel = computed(() =>
  [environment.value.provider, environment.value.label].filter(Boolean).join(" · ") || "检测中",
);
const sampledAt = computed(() => (fast.value ? fmtTime(fast.value.generated_at) : "—"));
const cpuShort = computed(() => (system.value.cpu_model || "—").replace(/\s+Processor$/i, ""));
const memoryText = computed(() => {
  const modules = system.value.memory_modules || [];
  const types = [...new Set(modules.map((m) => m.type).filter(Boolean))];
  const speeds = [...new Set(modules.map((m) => m.speed).filter(Boolean))];
  return [fast.value ? fmtBytes(fast.value.memory.total_bytes) : null, ...types, ...speeds].filter(Boolean).join(" · ") || "—";
});
const networkText = computed(() => {
  const addresses = (network.value.addresses || []).filter((item) => !item.includes(":"));
  return [...addresses, network.value.interface || fast.value?.network.interface].filter(Boolean).join(" · ") || "—";
});
const kernelText = computed(() => [system.value.kernel, system.value.architecture].filter(Boolean).join(" · ") || "—");
const uptimeText = computed(() => duration(fast.value?.uptime_seconds));
const environmentText = computed(() => [system.value.timezone, environment.value.label].filter(Boolean).join(" · ") || "—");

const ready = computed(() => services.value.filter((item) => item.ok).length);
const serviceSummary = computed(() => `${ready.value} / ${services.value.length} 正常`);
const serviceTone = computed(() =>
  !services.value.length ? "" : ready.value === services.value.length ? "good" : "warn",
);
const fdTone = computed(() =>
  (health.value.fd_percent || 0) >= 90 ? "red" : (health.value.fd_percent || 0) >= 75 ? "amber" : "green",
);
const iowaitText = computed(() =>
  fast.value?.cpu?.iowait_percent != null ? `${num(fast.value.cpu.iowait_percent)}%` : "—",
);
const stealText = computed(() =>
  fast.value?.cpu?.steal_percent != null ? `${num(fast.value.cpu.steal_percent)}%` : "—",
);
</script>
