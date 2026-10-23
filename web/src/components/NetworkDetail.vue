<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-stats">
        <div><span>下载</span><b>{{ fmtRate(network.rx_bps) }}</b></div>
        <div><span>上传</span><b>{{ fmtRate(network.tx_bps) }}</b></div>
        <div><span>接口</span><b>{{ info.interface || "无默认出口" }}</b></div>
        <div><span>连接状态</span><b>{{ stateText }}</b></div>
      </div>
    </section>

    <section class="detail-section">
      <h3>接口信息</h3>
      <table class="dtable">
        <tbody>
          <tr><td>接口名称</td><td class="num mono">{{ info.interface || "—" }}</td></tr>
          <tr><td>协商速率</td><td class="num mono">{{ info.speed_mbps ? `${info.speed_mbps} Mb/s` : "—" }}</td></tr>
          <tr><td>双工模式</td><td class="num mono">{{ info.duplex === "full" ? "全双工" : info.duplex === "half" ? "半双工" : "—" }}</td></tr>
          <tr><td>IP 地址</td><td class="num mono">{{ (info.addresses || []).join(" · ") || "—" }}</td></tr>
        </tbody>
      </table>
    </section>

    <section class="detail-section">
      <h3>当前流量</h3>
      <table class="dtable">
        <tbody>
          <tr><td>接收速率</td><td class="num mono">{{ fmtRate(network.rx_bps) }}</td></tr>
          <tr><td>发送速率</td><td class="num mono">{{ fmtRate(network.tx_bps) }}</td></tr>
          <tr><td>采样时间</td><td class="num mono">{{ sampledAt }}</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, inject } from "vue";
import { fmtRate, fmtTime } from "../format";

const dash = inject("dash");
const info = computed(() => dash.groupData("network_info") || {});
const network = computed(() => dash.state.fast?.network || {});
const stateText = computed(() =>
  network.value.operstate === "up" ? "已连接" : network.value.operstate === "down" ? "未连接" : "状态未知",
);
const sampledAt = computed(() => (dash.state.fast ? fmtTime(dash.state.fast.generated_at) : "—"));
</script>
