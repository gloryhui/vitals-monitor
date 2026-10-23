<template>
  <div v-if="dash.alerts.value.length" class="status-strip" role="status">
    <span class="strip-title">{{ dash.alerts.value.length }} 项待处理</span>
    <span
      v-for="(alert, index) in dash.alerts.value"
      :key="index"
      class="strip-item"
      :class="alert.tone"
    >
      <i></i>{{ alert.text }}
    </span>
  </div>
</template>

<script setup>
import { inject } from "vue";

const dash = inject("dash");
</script>
