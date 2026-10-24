<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-section-head">
        <h3>温度传感器</h3>
        <span class="muted">{{ sensors.length }} 个</span>
      </div>
      <table class="dtable">
        <thead><tr><th>传感器</th><th>标签</th><th class="num">温度</th><th class="num">临界值</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="(item, index) in sensors" :key="index">
            <td class="mono">{{ item.chip }}</td>
            <td>{{ item.label }}</td>
            <td class="num mono" :class="{ bad: item.critical != null && item.value >= item.critical }">
              {{ num(item.value) }} °C
            </td>
            <td class="num mono">{{ item.critical != null ? `${num(item.critical)} °C` : "—" }}</td>
            <td>{{ item.critical != null && item.value >= item.critical ? "超过临界" : "正常" }}</td>
          </tr>
          <tr v-if="!sensors.length"><td colspan="5" class="muted">正在读取温度…</td></tr>
        </tbody>
      </table>
    </section>

    <section v-if="fans.length" class="detail-section">
      <h3>风扇转速</h3>
      <table class="dtable">
        <thead><tr><th>芯片</th><th>风扇</th><th class="num">转速</th><th class="num">范围</th></tr></thead>
        <tbody>
          <tr v-for="(item, index) in fans" :key="index">
            <td class="mono">{{ item.chip }}</td>
            <td>{{ item.label }}</td>
            <td class="num mono">{{ item.value }} RPM</td>
            <td class="num mono">{{ item.min ?? "—" }} ~ {{ item.max ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="voltages.length" class="detail-section">
      <h3>电压</h3>
      <table class="dtable">
        <thead><tr><th>芯片</th><th>电压轨</th><th class="num">当前</th><th class="num">范围</th></tr></thead>
        <tbody>
          <tr v-for="(item, index) in voltages" :key="index">
            <td class="mono">{{ item.chip }}</td>
            <td>{{ item.label }}</td>
            <td class="num mono">{{ item.value }} V</td>
            <td class="num mono">{{ item.min ?? "—" }} ~ {{ item.max ?? "—" }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="detail-section">
      <h3>磁盘温度</h3>
      <table class="dtable">
        <thead><tr><th>设备</th><th>型号</th><th>类型</th><th class="num">温度</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="disk in disks" :key="disk.device">
            <td class="mono">{{ disk.device }}</td>
            <td>{{ disk.model || "—" }}</td>
            <td>{{ disk.kind || "—" }}</td>
            <td class="num mono">{{ disk.temperature != null ? `${disk.temperature} °C` : "—" }}</td>
            <td>{{ disk.standby ? "休眠中" : disk.error ? "读取失败" : "正常" }}</td>
          </tr>
          <tr v-if="!disks.length"><td colspan="5" class="muted">暂无磁盘温度</td></tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<script setup>
import { computed, inject } from "vue";
import { num } from "../format";

const dash = inject("dash");
const allSensors = computed(() => dash.groupData("temperatures") || []);
const sensors = computed(() => allSensors.value.filter((item) => (item.kind || "temp") === "temp"));
const fans = computed(() => allSensors.value.filter((item) => item.kind === "fan"));
const voltages = computed(() => allSensors.value.filter((item) => item.kind === "voltage"));
const disks = computed(() => dash.groupData("smart") || []);
</script>
