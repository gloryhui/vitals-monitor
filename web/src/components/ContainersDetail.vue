<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-stats">
        <div><span>容器总数</span><b>{{ rows.length }}</b></div>
        <div><span>运行中</span><b>{{ running }}</b></div>
        <div><span>健康异常</span><b>{{ unhealthy }}</b></div>
        <div><span>Docker 空间</span><b>{{ dockerTotal }}</b></div>
      </div>
    </section>

    <section class="detail-section">
      <h3>容器列表</h3>
      <table class="dtable">
        <thead><tr><th>名称</th><th>镜像</th><th>状态</th><th>健康</th></tr></thead>
        <tbody>
          <tr v-for="item in paged" :key="item.name">
            <td class="mono">{{ item.name }}</td>
            <td class="mono">{{ item.image }}</td>
            <td>{{ stateLabel(item) }}</td>
            <td :class="tone(item)">{{ item.health || "—" }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="4" class="muted">正在读取容器…</td></tr>
        </tbody>
      </table>
    </section>

    <section class="detail-section">
      <h3>Docker 空间</h3>
      <table class="dtable">
        <thead><tr><th>类型</th><th class="num">大小</th><th class="num">可回收</th></tr></thead>
        <tbody>
          <tr v-for="row in docker" :key="row.Type">
            <td>{{ spaceLabel(row.Type) }}</td>
            <td class="num mono">{{ row.Size }}</td>
            <td class="num mono">{{ row.Reclaimable }}</td>
          </tr>
          <tr v-if="!docker.length"><td colspan="3" class="muted">暂无 Docker 空间数据</td></tr>
        </tbody>
      </table>
      <p class="note">可回收量由 Docker 估算，仅供查看。</p>
    </section>

    <div class="pager">
      <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="page -= 1">上一页</button>
      <span class="muted">第 {{ page }} / {{ pageCount }} 页 · 共 {{ rows.length }} 个</span>
      <button class="btn btn-sm" type="button" :disabled="page >= pageCount" @click="page += 1">下一页</button>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, ref, watch } from "vue";

const dash = inject("dash");
const rows = computed(() => dash.groupData("containers") || []);
const page = ref(1);
const pageSize = 10;
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / pageSize)));
const paged = computed(() => rows.value.slice((page.value - 1) * pageSize, page.value * pageSize));
watch(pageCount, (count) => { if (page.value > count) page.value = count; });
const docker = computed(() => dash.groupData("docker_usage") || []);
const running = computed(() => rows.value.filter((item) => item.state === "running").length);
const unhealthy = computed(() => rows.value.filter((item) => item.health === "unhealthy").length);
const dockerTotal = computed(() => docker.value.reduce((sum, row) => sum + parseFloat(row.Size || 0), 0).toFixed(1) + " GB");
const spaceLabel = (type) =>
  ({ Images: "镜像", Containers: "容器", "Local Volumes": "数据卷", "Build Cache": "构建缓存" })[type] || type;

const stateLabel = (item) => {
  if (item.state === "running") {
    if (item.health === "unhealthy") return "健康检查异常";
    if (item.health === "starting") return "健康检查中";
    if (item.health === "healthy") return "运行正常";
    return "运行中";
  }
  return (
    { exited: "已停止", created: "未启动", paused: "已暂停", restarting: "重启中", dead: "异常退出", removing: "移除中" }[
      item.state
    ] || "状态未知"
  );
};
const tone = (item) =>
  item.health === "unhealthy" || item.state === "dead"
    ? "bad"
    : item.state === "restarting" || item.health === "starting"
      ? "warn"
      : item.state === "running"
        ? "good"
        : "muted";
</script>
