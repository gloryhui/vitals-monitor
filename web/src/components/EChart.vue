<template>
  <div ref="host" class="echart"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

const props = defineProps({
  option: { type: Object, required: true },
});

const host = ref(null);
let chart = null;
let observer = null;

onMounted(() => {
  chart = echarts.init(host.value, null, { renderer: "canvas" });
  chart.setOption(props.option);
  observer = new ResizeObserver(() => chart?.resize());
  observer.observe(host.value);
});

watch(
  () => props.option,
  (option) => chart?.setOption(option, { notMerge: true }),
  { deep: true },
);

onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
  chart = null;
});
</script>

<style scoped>
.echart {
  width: 100%;
  height: 100%;
}
</style>
