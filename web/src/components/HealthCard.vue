<template>
  <section class="card">
    <div class="card-head">
      <h2>系统健康</h2>
      <span class="pill" :class="{ warn: state.stale }">{{ statusText }}</span>
    </div>
    <div class="health-grid">
      <div>
        <span>文件描述符</span>
        <strong>{{ health.fd_used != null ? `${health.fd_used} / ${health.fd_max}` : "—" }}</strong>
        <div class="meter" :class="fdTone"><i :style="{ width: `${health.fd_percent || 0}%` }"></i></div>
      </div>
      <div><span>僵尸进程</span><strong :class="{ bad: health.zombies > 0 }">{{ health.zombies ?? "—" }}</strong></div>
      <div>
        <span>systemd 失败单元</span>
        <strong :class="{ bad: health.systemd_failed > 0 }">{{ health.systemd_failed ?? "—" }}</strong>
      </div>
      <div><span>TCP 已建立</span><strong>{{ health.tcp_established ?? "—" }}</strong></div>
      <div><span>CPU iowait</span><strong>{{ iowaitText }}</strong></div>
      <div><span>CPU steal</span><strong>{{ stealText }}</strong></div>
    </div>
  </section>
</template>

<script setup>
import { computed, inject } from "vue";
import { num } from "../format";

const dash = inject("dash");
const state = computed(() => dash.groupState("host_health") || {});
const health = computed(() => dash.groupData("host_health") || {});
const statusText = computed(() => dash.groupStatus("host_health"));
const fast = computed(() => dash.state.fast || {});
const iowaitText = computed(() => (fast.value.cpu?.iowait_percent != null ? `${num(fast.value.cpu.iowait_percent)}%` : "—"));
const stealText = computed(() => (fast.value.cpu?.steal_percent != null ? `${num(fast.value.cpu.steal_percent)}%` : "—"));
const fdTone = computed(() =>
  (health.value.fd_percent || 0) >= 90 ? "red" : (health.value.fd_percent || 0) >= 75 ? "amber" : "green",
);
</script>
