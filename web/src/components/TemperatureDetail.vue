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
const sensors = computed(() => dash.groupData("temperatures") || []);
const disks = computed(() => dash.groupData("smart") || []);
</script>
