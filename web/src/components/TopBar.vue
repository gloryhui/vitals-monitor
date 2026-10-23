<template>
  <header class="topbar">
    <div class="brand">
      <span class="brand-mark">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <rect x="3" y="4" width="18" height="7" rx="2" />
          <rect x="3" y="13" width="18" height="7" rx="2" />
          <path d="M7 7.5h.01M7 16.5h.01" />
        </svg>
      </span>
      Vitals
    </div>
    <div class="top-actions">
      <div class="clock">
        <strong>{{ clock }}</strong>
        <span>{{ lunar }}</span>
      </div>
      <span class="who" :title="dash.state.username">{{ dash.state.username }}</span>
      <button class="btn" type="button" @click="dash.toggleTheme()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
          <path v-if="dash.state.theme === 'dark'" d="M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" />
          <path v-else d="M21 13a9 9 0 0 1-10-10A9 9 0 1 0 21 13Z" />
        </svg>
        {{ dash.state.theme === "dark" ? "亮色" : "深色" }}
      </button>
      <button class="btn" type="button" @click="dash.logout()">退出</button>
    </div>
  </header>
</template>

<script setup>
import { inject } from "vue";

defineProps({
  clock: { type: String, default: "" },
  lunar: { type: String, default: "" },
});

const dash = inject("dash");
</script>
