<template>
  <div v-if="!dash.state.ready" class="boot">正在验证登录状态…</div>
  <LoginView v-else-if="!dash.state.authenticated" />
  <div v-else class="shell">
    <TopBar :clock="clock" :lunar="lunar" />
    <HeroPanel />
    <StatusStrip />
    <SystemOverview @detail="openDetail('services')" />
    <ResourceSection @zoom="openZoom" @detail="openDetail" />
    <EventsCard />
    <FooterBar />
  </div>
  <ChartModal v-if="zoomChart" :chart="zoomChart" @close="closeZoom" />
  <DetailDrawer v-if="detailKey" :detail="detailKey" @close="detailKey = null" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, provide, ref } from "vue";
import { createDashboard } from "./useDashboard";
import { CHARTS } from "./charts";
import TopBar from "./components/TopBar.vue";
import HeroPanel from "./components/HeroPanel.vue";
import ResourceSection from "./components/ResourceSection.vue";
import EventsCard from "./components/EventsCard.vue";
import FooterBar from "./components/FooterBar.vue";
import ChartModal from "./components/ChartModal.vue";
import StatusStrip from "./components/StatusStrip.vue";
import SystemOverview from "./components/SystemOverview.vue";
import DetailDrawer from "./components/DetailDrawer.vue";
import LoginView from "./components/LoginView.vue";

const dash = createDashboard();
provide("dash", dash);

const clock = ref("");
const lunar = ref("");
const zoomChart = ref(null);
const detailKey = ref(null);
let timer = null;

function updateClock() {
  const now = new Date();
  clock.value = now.toLocaleString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  try {
    lunar.value = new Intl.DateTimeFormat("zh-CN-u-ca-chinese", {
      year: "numeric",
      month: "long",
      day: "numeric",
    }).format(now);
  } catch (_) {
    lunar.value = "";
  }
  dash.tick();
}

function openZoom(chartId) {
  zoomChart.value = CHARTS[chartId] || null;
}

function closeZoom() {
  zoomChart.value = null;
}

function openDetail(key) {
  detailKey.value = key;
}

function onVisibility() {
  if (document.hidden) dash.pausePollers();
  else if (dash.state.authenticated) dash.startPollers();
}

onMounted(() => {
  document.documentElement.dataset.theme = dash.state.theme;
  updateClock();
  timer = setInterval(updateClock, 1000);
  dash.bootstrap();
  document.addEventListener("visibilitychange", onVisibility);
});

onBeforeUnmount(() => {
  clearInterval(timer);
  document.removeEventListener("visibilitychange", onVisibility);
});
</script>
