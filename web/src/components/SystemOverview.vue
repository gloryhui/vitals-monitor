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
      <div class="basics-row">
        <div class="basics-primary">
          <div class="key-fact">
            <strong>{{ system.os || "—" }}</strong>
            <span>操作系统</span>
          </div>
          <div class="key-fact">
            <strong>{{ cpuShort }}</strong>
            <span>处理器 · {{ system.cpu_threads }} 线程</span>
          </div>
          <div class="key-fact">
            <strong>{{ memoryText }}</strong>
            <span>内存配置</span>
          </div>
          <div class="key-fact">
            <strong>{{ uptimeText }}</strong>
            <span>运行时间</span>
          </div>
        </div>
        <div class="basics-secondary">
          <div><span>网络地址</span><strong>{{ networkText }}</strong></div>
          <div><span>内核 / 架构</span><strong>{{ kernelText }}</strong></div>
          <div><span>主板</span><strong>{{ system.board || "—" }}</strong></div>
          <div><span>时区 / 环境</span><strong>{{ environmentText }}</strong></div>
        </div>
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
      <p class="note">每 15 秒检查一次，连续失败 3 次记异常，连续成功 2 次记恢复。</p>
    </div>

    <div class="overview-row">
      <div class="row-head">
        <span class="row-kicker">系统健康</span>
      </div>
      <div class="health-row">
        <div class="health-main">
          <span class="health-label">文件描述符</span>
          <strong class="health-big">{{ health.fd_used ?? "—" }}<small> / {{ health.fd_max ?? "—" }}</small></strong>
          <div class="meter" :class="fdTone"><i :style="{ width: `${health.fd_percent || 0}%` }"></i></div>
          <span class="health-pct">已使用 {{ health.fd_percent ?? "—" }}%</span>
        </div>
        <div class="health-facts">
          <div><span>僵尸进程</span><b :class="{ bad: health.zombies > 0 }">{{ health.zombies ?? "—" }}</b></div>
          <div><span>systemd 失败</span><b :class="{ bad: health.systemd_failed > 0 }">{{ health.systemd_failed ?? "—" }}</b></div>
          <div><span>TCP 已建立</span><b>{{ health.tcp_established ?? "—" }}</b></div>
          <div><span>OOM 次数</span><b :class="{ bad: health.oom_kill > 0 }">{{ health.oom_kill ?? "—" }}</b></div>
          <div><span>CPU iowait</span><b>{{ iowaitText }}</b></div>
          <div><span>CPU steal</span><b>{{ stealText }}</b></div>
        </div>
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
