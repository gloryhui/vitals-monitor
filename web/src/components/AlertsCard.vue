<template>
  <section class="card">
    <div class="card-head">
      <h2>当前状态 <span class="pill" :class="alertTone">{{ dash.alerts.value.length ? `${dash.alerts.value.length} 项` : dash.allReady.value ? "正常" : "检查中" }}</span></h2>
    </div>
    <ul v-if="dash.alerts.value.length" class="alerts-list">
      <li v-for="(alert, index) in dash.alerts.value" :key="index" class="alert-item" :class="alert.tone">
        {{ alert.text }}
      </li>
    </ul>
    <p v-else class="all-clear">{{ dash.allReady.value ? "当前未发现持续异常。" : "正在读取服务器状态…" }}</p>
  </section>
</template>

<script setup>
import { computed, inject } from "vue";

const dash = inject("dash");
const alertTone = computed(() => {
  if (dash.alerts.value.length) return "warn";
  return dash.allReady.value ? "good" : "";
});
</script>
