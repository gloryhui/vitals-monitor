<template>
  <article class="card full">
    <div class="card-head">
      <h2>存储</h2>
      <div class="card-tools">
        <span class="muted" style="font-size: 11px">容量与健康分开更新</span>
        <button class="btn btn-sm" type="button" @click="$emit('detail')">详情</button>
      </div>
    </div>
    <div class="card-body">
      <ChartBlock
        chart-id="chartDisk"
        :keys="chart.keys"
        :max="chart.max"
        :format="chart.format"
        :labels="chart.labels"
        @zoom="$emit('zoom', chart.id)"
      />

      <div class="storage-columns">
        <section>
          <div class="storage-label">
            <h3>分区容量</h3>
            <span class="pill" :class="{ warn: fsState.stale }">{{ fsStatus }}</span>
          </div>
          <div v-for="fs in filesystems" :key="fs.mount" class="fs-row" :title="`${fs.source} · ${fs.type}`">
            <div class="fs-top">
              <b class="mono">{{ fs.mount }}</b>
              <span :class="fsTone(fs)">{{ fs.used_percent }}%</span>
            </div>
            <div class="meter" :class="meterClass(fs)">
              <i :style="{ width: `${Math.min(100, fs.used_percent)}%` }"></i>
            </div>
            <div class="fs-meta">
              <span>{{ fmtBytes(fs.used_bytes) }} / {{ fmtBytes(fs.size_bytes) }}</span>
              <span>可用 {{ fmtBytes(fs.avail_bytes) }}</span>
            </div>
          </div>
          <div v-if="!filesystems.length" class="note">正在读取分区容量…</div>
        </section>

        <section>
          <div class="storage-label">
            <h3>磁盘健康</h3>
            <span class="pill" :class="{ warn: smartState.stale }">{{ smartStatus }}</span>
          </div>
          <div v-for="disk in disks" :key="disk.device" class="disk">
            <div class="disk-top">
              <div>
                <div class="disk-name">{{ disk.model || disk.device }}</div>
                <div class="disk-device">
                  {{ disk.device }} · {{ disk.kind || "磁盘" }}
                  <template v-if="disk.size_bytes"> · {{ fmtBytes(disk.size_bytes) }}</template>
                </div>
              </div>
              <span class="pill" :class="healthTone(disk)[0]">{{ healthTone(disk)[1] }}</span>
            </div>
            <p v-if="disk.standby || disk.error" class="note">
              {{ disk.standby ? "磁盘正在休眠，本轮不唤醒读取。" : "本轮未能读取磁盘健康数据。" }}
            </p>
            <template v-else>
              <div class="disk-stats">
                <span>温度 <b>{{ disk.temperature != null ? `${disk.temperature} °C` : "—" }}</b></span>
                <span>通电 <b>{{ disk.power_on_hours != null ? `${disk.power_on_hours.toLocaleString("zh-CN")} 小时` : "—" }}</b></span>
                <span v-if="disk.percentage_used != null">寿命消耗 <b>{{ disk.percentage_used }}%</b></span>
              </div>
              <details>
                <summary>更多健康指标</summary>
                <dl class="kv">
                  <template v-if="disk.kind === 'NVMe'">
                    <dt>可用备用空间</dt><dd>{{ disk.available_spare != null ? `${disk.available_spare}%` : "—" }}</dd>
                    <dt>介质错误</dt><dd>{{ disk.media_errors ?? "—" }}</dd>
                    <dt>异常断电次数</dt><dd>{{ disk.unsafe_shutdowns ?? "—" }}</dd>
                    <dt>累计写入</dt><dd>{{ fmtBytes(disk.written_bytes) }}</dd>
                  </template>
                  <template v-else>
                    <dt>重映射扇区</dt><dd>{{ disk.reallocated_sectors ?? "—" }}</dd>
                    <dt>待映射扇区</dt><dd>{{ disk.pending_sectors ?? "—" }}</dd>
                    <dt>不可校正扇区</dt><dd>{{ disk.uncorrectable_sectors ?? "—" }}</dd>
                    <dt>传输 CRC 错误</dt><dd>{{ disk.udma_crc_errors ?? "—" }}</dd>
                  </template>
                </dl>
                <p class="note">错误与断电次数为累计值，不代表本轮新增。</p>
              </details>
            </template>
          </div>
          <div v-if="!disks.length" class="note">正在读取 SMART…</div>
        </section>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed, inject } from "vue";
import ChartBlock from "./ChartBlock.vue";
import { CHARTS } from "../charts";
import { fmtBytes } from "../format";

defineEmits(["zoom", "detail"]);

const dash = inject("dash");
const chart = CHARTS.chartDisk;
const filesystems = computed(() => dash.groupData("filesystems") || []);
const disks = computed(() => dash.groupData("smart") || []);
const fsState = computed(() => dash.groupState("filesystems"));
const smartState = computed(() => dash.groupState("smart"));
const fsStatus = computed(() => dash.groupStatus("filesystems"));
const smartStatus = computed(() => dash.groupStatus("smart"));

const limit = computed(() => dash.state.alertPolicy.filesystem_percent || 90);
const warn = computed(() => Math.max(0, limit.value - 10));
const fsTone = (fs) =>
  fs.used_percent >= limit.value ? "bad" : fs.used_percent >= warn.value ? "warn" : "mono";
const meterClass = (fs) =>
  fs.used_percent >= limit.value ? "danger" : fs.used_percent >= warn.value ? "warning" : "";

function healthTone(disk) {
  if (disk.standby) return ["muted", "休眠中"];
  if (disk.error) return ["warn", "无法读取"];
  if (
    disk.passed === false ||
    (disk.media_errors || 0) > 0 ||
    (disk.pending_sectors || 0) > 0 ||
    (disk.uncorrectable_sectors || 0) > 0
  )
    return ["bad", "需要关注"];
  if ((disk.reallocated_sectors || 0) > 0 || (disk.percentage_used || 0) >= 90)
    return ["warn", "需要关注"];
  return disk.passed === true ? ["good", "健康正常"] : ["muted", "状态未知"];
}
</script>
