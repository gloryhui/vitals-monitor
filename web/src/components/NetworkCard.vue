<template>
  <article class="card">
    <div class="card-head">
      <h2>网络</h2>
      <span class="pill" :class="{ warn: state.stale }">{{ statusText }}</span>
    </div>
    <div class="card-body">
      <div class="metric">
        <span class="metric-value">↓ {{ fmtRate(network.rx_bps) }}</span>
      </div>
      <div class="metric-sub">↑ {{ fmtRate(network.tx_bps) }} · {{ interfaceText }}</div>

      <ChartBlock
        chart-id="chartNetwork"
        title="网络流量"
        :keys="chart.keys"
        :max="chart.max"
        :format="chart.format"
        :labels="chart.labels"
        @zoom="$emit('zoom', chart.id)"
      />

      <dl class="kv">
        <dt>接口</dt><dd>{{ info.interface || "无默认出口" }}</dd>
        <dt>协商速率</dt>
        <dd>{{ info.speed_mbps ? `${info.speed_mbps} Mb/s${info.duplex === "full" ? " · 全双工" : info.duplex === "half" ? " · 半双工" : ""}` : "—" }}</dd>
        <dt>IP 地址</dt><dd>{{ (info.addresses || []).join(" · ") || "—" }}</dd>
      </dl>
    </div>
  </article>
</template>

<script setup>
import { computed, inject } from "vue";
import ChartBlock from "./ChartBlock.vue";
import { CHARTS } from "../charts";
import { fmtRate } from "../format";

defineEmits(["zoom"]);

const dash = inject("dash");
const chart = CHARTS.chartNetwork;
const info = computed(() => dash.groupData("network_info") || {});
const state = computed(() => dash.groupState("network_info"));
const statusText = computed(() => dash.groupStatus("network_info"));
const network = computed(() => dash.state.fast?.network || {});
const interfaceText = computed(() => {
  const interfaceName = network.value.interface || info.value.interface || "无默认出口";
  const stateText =
    network.value.operstate === "up" ? "已连接" : network.value.operstate === "down" ? "未连接" : "状态未知";
  return `${interfaceName} · ${stateText}`;
});
</script>
