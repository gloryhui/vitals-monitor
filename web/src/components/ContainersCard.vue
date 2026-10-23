<template>
  <article class="card">
    <div class="card-head">
      <h2>容器</h2>
      <span class="pill" :class="{ warn: state.stale }">{{ statusText }}</span>
    </div>
    <div class="card-body">
      <div class="metric">
        <span class="metric-value">{{ running }}<small>个运行中</small></span>
      </div>
      <div class="metric-sub">{{ counts }}</div>

      <input v-model="query" class="search" type="search" placeholder="筛选容器名称…" autocomplete="off" />
      <div class="container-list">
        <div v-for="item in filtered" :key="item.name" class="container-row" :title="`${item.image} · ${item.status}`">
          <i class="container-dot" :class="tone(item)"></i>
          <span class="mono">{{ item.name }}</span>
          <span class="container-state">{{ stateLabel(item) }}</span>
        </div>
        <div v-if="!filtered.length" class="note">
          {{ query ? "没有匹配的容器" : rows.length ? "—" : "正在读取容器…" }}
        </div>
      </div>

      <div class="docker-space">
        <div>镜像占用<b>{{ space("Images") }}</b></div>
        <div>构建缓存<b>{{ space("Build Cache") }}</b></div>
        <div>数据卷<b>{{ space("Local Volumes") }}</b></div>
      </div>
      <details>
        <summary>空间统计</summary>
        <dl class="kv">
          <template v-for="row in docker" :key="row.Type">
            <dt>{{ spaceLabel(row.Type) }}</dt><dd>{{ row.Size }} · 可回收 {{ row.Reclaimable }}</dd>
          </template>
        </dl>
        <p class="note">可回收量由 Docker 估算，仅供查看。</p>
      </details>
    </div>
  </article>
</template>

<script setup>
import { computed, inject, ref } from "vue";

const dash = inject("dash");
const query = ref("");
const rows = computed(() => dash.groupData("containers") || []);
const docker = computed(() => dash.groupData("docker_usage") || []);
const state = computed(() => dash.groupState("containers"));
const statusText = computed(() => dash.groupStatus("containers"));
const running = computed(() => rows.value.filter((item) => item.state === "running").length);
const unhealthy = computed(() => rows.value.filter((item) => item.health === "unhealthy").length);
const counts = computed(
  () => `运行中 / 共 ${rows.value.length} 个${unhealthy.value ? ` · ${unhealthy.value} 个健康检查异常` : ""}`,
);
const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return rows.value.filter((item) => item.name.toLowerCase().includes(needle));
});
const space = (type) => docker.value.find((row) => row.Type === type)?.Size || "—";
const spaceLabel = (type) =>
  ({ Images: "镜像", Containers: "容器", "Local Volumes": "数据卷", "Build Cache": "构建缓存" })[type] || type;

const labelFor = (item) => {
  if (item.state === "running") {
    if (item.health === "unhealthy") return "健康检查异常";
    if (item.health === "starting") return "健康检查中";
    if (item.health === "healthy") return "运行正常";
    return "运行中";
  }
  return (
    {
      exited: "已停止",
      created: "未启动",
      paused: "已暂停",
      restarting: "重启中",
      dead: "异常退出",
      removing: "移除中",
    }[item.state] || "状态未知"
  );
};
const stateLabel = (item) => labelFor(item);
const tone = (item) =>
  item.health === "unhealthy" || item.state === "dead"
    ? "bad"
    : item.state === "restarting" || item.health === "starting"
      ? "warn"
      : item.state === "running"
        ? "good"
        : "";
</script>
