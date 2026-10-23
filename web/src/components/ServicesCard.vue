<template>
  <section class="card">
    <div class="card-head">
      <h2>服务检查 <span class="pill" :class="summaryTone">{{ summary }}</span></h2>
      <span class="pill" :class="{ warn: state.stale }">{{ statusText }}</span>
    </div>
    <div class="card-body">
      <div v-if="services.length" class="service-grid">
        <article v-for="item in services" :key="item.id" class="service">
          <div class="service-title" :class="item.ok ? 'good' : 'bad'">
            <i :class="{ bad: !item.ok }"></i><span>{{ item.name }}</span>
          </div>
          <div class="service-result">
            <span :class="item.ok ? 'good' : 'bad'">{{ item.detail }}</span>
            <span class="mono muted">{{ item.latency_ms }} ms</span>
          </div>
          <div class="service-target">{{ item.target || "—" }}</div>
          <div v-if="item.consecutive_failures" class="note">连续失败 {{ item.consecutive_failures }} 次</div>
        </article>
      </div>
      <div v-else class="note">正在检查服务…</div>
      <p class="note">
        每 15 秒检查 · 连续失败 {{ dash.state.alertPolicy.service_failures || 3 }} 次记异常，连续成功
        {{ dash.state.alertPolicy.service_recoveries || 2 }} 次记恢复
      </p>
    </div>
  </section>
</template>

<script setup>
import { computed, inject } from "vue";

const dash = inject("dash");
const state = computed(() => dash.groupState("services"));
const services = computed(() => state.value.data || []);
const summary = computed(() => {
  if (state.value.stale) return "状态已过期";
  if (!services.value.length) return "未配置";
  return `${services.value.filter((item) => item.ok).length} / ${services.value.length} 项正常`;
});
const summaryTone = computed(() => {
  if (state.value.stale) return "warn";
  return services.value.length && services.value.every((item) => item.ok) ? "good" : "";
});
const statusText = computed(() => dash.groupStatus("services"));
</script>
