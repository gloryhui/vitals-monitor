<template>
  <div class="chart-head">
    <h3 v-if="title">{{ title }}</h3>
    <div class="chart-tools">
      <div v-if="labels" class="legend">
        <span v-for="key in displayKeys" :key="key">
          <i :style="{ background: colorOf(key) }"></i>{{ labels[key] || key }}
          <b>{{ legendValue(key) }}</b>
        </span>
      </div>
      <select
        class="select"
        :value="range"
        :aria-label="`${title || chartId} 时间范围`"
        @change="onRange"
      >
        <option v-for="value in RANGE_OPTIONS" :key="value" :value="value">
          {{ rangeLabel(value) }}
        </option>
      </select>
      <button
        v-if="zoomable"
        class="btn btn-icon"
        type="button"
        :aria-label="`放大${title || '趋势'}`"
        title="放大查看"
        @click="$emit('zoom', chartId)"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
          <path d="M4 9V4h5M20 15v5h-5M15 4h5v5M9 20H4v-5" />
        </svg>
      </button>
    </div>
  </div>
  <div class="chart-box" :class="{ tall }">
    <EChart :option="option" />
    <div v-if="!hasData" class="chart-empty">正在积累采样数据…</div>
  </div>
</template>

<script setup>
import { computed, inject } from "vue";
import EChart from "./EChart.vue";
import { buildChartOption } from "../chartOption";
import { RANGE_OPTIONS, finite, rangeLabel } from "../format";

const props = defineProps({
  chartId: { type: String, required: true },
  title: { type: String, default: "" },
  keys: { type: Array, required: true },
  max: { type: Number, default: null },
  format: { type: Function, required: true },
  labels: { type: Object, default: null },
  tall: { type: Boolean, default: false },
  zoomable: { type: Boolean, default: true },
});

defineEmits(["zoom"]);

const dash = inject("dash");
const range = computed(
  () => dash.state.chartRanges[props.chartId] || dash.state.globalRange,
);

const displayKeys = computed(() => {
  if (props.chartId !== "chartTemp") return props.keys;
  return props.keys.filter((key) => dash.temperatureKeys.value.has(key));
});

const points = computed(() => dash.chartPoints(props.chartId));
const interval = computed(() => dash.chartInterval(props.chartId));
const latest = computed(() => points.value[points.value.length - 1] || null);

const palette = computed(() => {
  dash.state.theme;
  const style = getComputedStyle(document.documentElement);
  const read = (name) => style.getPropertyValue(name).trim();
  return [
    read("--brand"),
    read("--green"),
    read("--amber"),
    read("--violet"),
    read("--red"),
    "#17899b",
  ];
});

const colorOf = (key) => palette.value[displayKeys.value.indexOf(key)];

const legendValue = (key) => {
  const value = latest.value?.[key];
  return finite(value) ? props.format(value) : "—";
};

const hasData = computed(() =>
  points.value.some((point) => displayKeys.value.some((key) => finite(point[key]))),
);

const option = computed(() => {
  const style = getComputedStyle(document.documentElement);
  const read = (name) => style.getPropertyValue(name).trim();
  return buildChartOption({
    points: points.value,
    keys: displayKeys.value,
    labels: props.labels || Object.fromEntries(displayKeys.value.map((key) => [key, key])),
    colors: palette.value,
    max: props.max,
    format: props.format,
    interval: interval.value,
    large: props.zoomable === false,
    muted: read("--muted"),
    line: read("--line"),
    surface: read("--surface"),
    text: read("--text"),
  });
});

const onRange = (event) => dash.setChartRange(props.chartId, event.target.value);
</script>
