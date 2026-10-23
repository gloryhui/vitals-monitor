<template>
  <div class="detail-grid">
    <section class="detail-section">
      <h3>分区容量</h3>
      <table class="dtable">
        <thead>
          <tr><th>挂载点</th><th>设备</th><th>类型</th><th class="num">已用 / 总量</th><th class="num">可用</th><th class="num">使用率</th></tr>
        </thead>
        <tbody>
          <tr v-for="fs in filesystems" :key="fs.mount">
            <td class="mono">{{ fs.mount }}</td>
            <td class="mono">{{ fs.source }}</td>
            <td>{{ fs.type }}</td>
            <td class="num mono">{{ fmtBytes(fs.used_bytes) }} / {{ fmtBytes(fs.size_bytes) }}</td>
            <td class="num mono">{{ fmtBytes(fs.avail_bytes) }}</td>
            <td class="num mono" :class="fsTone(fs)">{{ fs.used_percent }}%</td>
          </tr>
          <tr v-if="!filesystems.length"><td colspan="6" class="muted">正在读取分区…</td></tr>
        </tbody>
      </table>
    </section>

    <section v-for="disk in disks" :key="disk.device" class="detail-section">
      <div class="detail-section-head">
        <h3>{{ disk.model || disk.device }}</h3>
        <span class="pill" :class="healthTone(disk)[0]">{{ healthTone(disk)[1] }}</span>
      </div>
      <p class="note">{{ disk.device }} · {{ disk.kind || "磁盘" }} · {{ fmtBytes(disk.size_bytes) }}</p>
      <table class="dtable">
        <tbody>
          <tr><td>温度</td><td class="num mono">{{ disk.temperature != null ? `${disk.temperature} °C` : "—" }}</td></tr>
          <tr><td>通电时间</td><td class="num mono">{{ disk.power_on_hours != null ? `${disk.power_on_hours.toLocaleString("zh-CN")} 小时` : "—" }}</td></tr>
          <tr><td>寿命消耗</td><td class="num mono">{{ disk.percentage_used != null ? `${disk.percentage_used}%` : "—" }}</td></tr>
          <template v-if="disk.kind === 'NVMe'">
            <tr><td>可用备用空间</td><td class="num mono">{{ disk.available_spare != null ? `${disk.available_spare}%` : "—" }}</td></tr>
            <tr><td>介质错误</td><td class="num mono">{{ disk.media_errors ?? "—" }}</td></tr>
            <tr><td>异常断电次数</td><td class="num mono">{{ disk.unsafe_shutdowns ?? "—" }}</td></tr>
            <tr><td>累计写入</td><td class="num mono">{{ fmtBytes(disk.written_bytes) }}</td></tr>
          </template>
          <template v-else>
            <tr><td>重映射扇区</td><td class="num mono">{{ disk.reallocated_sectors ?? "—" }}</td></tr>
            <tr><td>待映射扇区</td><td class="num mono">{{ disk.pending_sectors ?? "—" }}</td></tr>
            <tr><td>不可校正扇区</td><td class="num mono">{{ disk.uncorrectable_sectors ?? "—" }}</td></tr>
            <tr><td>传输 CRC 错误</td><td class="num mono">{{ disk.udma_crc_errors ?? "—" }}</td></tr>
          </template>
        </tbody>
      </table>
    </section>
    <p v-if="!disks.length" class="note">正在读取 SMART…</p>
  </div>
</template>

<script setup>
import { computed, inject } from "vue";
import { fmtBytes } from "../format";

const dash = inject("dash");
const filesystems = computed(() => dash.groupData("filesystems") || []);
const disks = computed(() => dash.groupData("smart") || []);
const limit = computed(() => dash.state.alertPolicy.filesystem_percent || 90);
const fsTone = (fs) =>
  fs.used_percent >= limit.value ? "bad" : fs.used_percent >= limit.value - 10 ? "warn" : "mono";

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
