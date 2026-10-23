<template>
  <section class="hero">
    <div>
      <p class="eyebrow">{{ provider ? `${provider} · ` : "" }}本机监控</p>
      <h1>{{ hostname }} <em>状态概览</em></h1>
      <p class="subtitle">{{ subtitle }}</p>
    </div>
    <div class="hero-actions">
      <span class="pill" :class="healthTone">{{ healthText }}</span>
      <span class="live" :class="liveTone" role="status">
        <i></i>{{ liveText }}
      </span>
      <label for="refreshInterval" class="sr-only">实时指标刷新间隔</label>
      <select
        id="refreshInterval"
        class="select"
        :value="dash.state.refreshMs"
        aria-label="实时指标刷新间隔"
        @change="dash.setRefreshMs($event.target.value)"
      >
        <option :value="1000">每 1 秒刷新</option>
        <option :value="5000">每 5 秒刷新</option>
        <option :value="10000">每 10 秒刷新</option>
        <option :value="30000">每 30 秒刷新</option>
      </select>
      <button class="btn" type="button" @click="dash.refreshAll()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
          <path d="M20 7v5h-5M4 17v-5h5" />
          <path d="M6 6a8 8 0 0 1 13 3M5 15a8 8 0 0 0 13 3" />
        </svg>
        刷新
      </button>
    </div>
  </section>
</template>

<script setup>
import { computed, inject } from "vue";

const dash = inject("dash");

const system = computed(() => dash.groupData("system") || {});
const network = computed(() => dash.groupData("network_info") || {});
const environment = computed(() => system.value.environment || {});
const hostname = computed(() => system.value.hostname || dash.state.fast?.hostname || "服务器");
const provider = computed(() => environment.value.provider || "");
const subtitle = computed(() => {
  const parts = [environment.value.label, system.value.architecture, system.value.os].filter(Boolean);
  const address = (network.value.addresses || []).find((item) => !item.includes(":"));
  if (address) parts.push(address);
  return parts.length ? parts.join(" · ") : "正在读取系统信息…";
});

const liveTone = computed(() => (dash.online.value ? "" : dash.state.fast ? "warn" : "bad"));
const liveText = computed(() => {
  if (!dash.state.fast) return dash.state.fastError ? "连接失败" : "连接中";
  return dash.online.value ? "实时更新" : "数据已过期";
});

const healthTone = computed(() => {
  const alerts = dash.alerts.value;
  if (alerts.length) return alerts.some((item) => item.tone === "bad") ? "bad" : "warn";
  return dash.allReady.value ? "good" : "";
});

const healthText = computed(() => {
  const alerts = dash.alerts.value;
  if (alerts.length) return `${alerts.length} 项待处理`;
  return dash.allReady.value ? "运行正常" : "检查中";
});
</script>
