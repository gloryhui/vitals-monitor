<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-stats">
        <div><span>容器总数</span><b>{{ rows.length }}</b></div>
        <div><span>运行中</span><b>{{ running }}</b></div>
        <div><span>异常</span><b>{{ unhealthy }}</b></div>
        <div><span>镜像</span><b>{{ images.length }}</b></div>
        <div><span>未使用镜像</span><b>{{ unusedImages }}</b></div>
      </div>
    </section>

    <section class="detail-section">
      <div class="detail-section-head">
        <h3>容器</h3>
        <div class="detail-toolbar">
          <select v-model="stateFilter" class="select" aria-label="容器状态筛选">
            <option value="all">全部状态</option>
            <option value="running">运行中</option>
            <option value="stopped">已停止</option>
            <option value="bad">异常</option>
          </select>
          <input v-model="query" class="search inline" type="search" placeholder="筛选名称或镜像…" />
        </div>
      </div>
      <div class="table-wrap">
        <table class="dtable">
          <thead>
            <tr>
              <th>ID</th><th>名称</th><th>镜像</th><th>状态</th><th>端口</th><th>运行时长</th><th>命令</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in paged" :key="item.id || item.name">
              <td class="mono">{{ item.id || "—" }}</td>
              <td class="mono">{{ item.name }}</td>
              <td class="mono">{{ item.image }}</td>
              <td :class="tone(item)">{{ stateLabel(item) }}</td>
              <td class="mono">{{ item.ports || "—" }}</td>
              <td>{{ item.running_for || item.status }}</td>
              <td class="mono cmd" :title="item.command">{{ item.command || "—" }}</td>
            </tr>
            <tr v-if="!paged.length"><td colspan="7" class="muted">没有匹配的容器</td></tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <span class="muted">共 {{ filtered.length }} 个</span>
        <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="page -= 1">上一页</button>
        <span class="muted">第 {{ page }} / {{ pageCount }} 页</span>
        <button class="btn btn-sm" type="button" :disabled="page >= pageCount" @click="page += 1">下一页</button>
      </div>
    </section>

    <section class="detail-section">
      <div class="detail-section-head">
        <h3>镜像</h3>
        <div class="detail-toolbar">
          <div class="seg">
            <button type="button" :class="{ active: imageFilter === 'all' }" @click="imageFilter = 'all'">全部</button>
            <button type="button" :class="{ active: imageFilter === 'used' }" @click="imageFilter = 'used'">在用</button>
            <button type="button" :class="{ active: imageFilter === 'unused' }" @click="imageFilter = 'unused'">未使用</button>
          </div>
        </div>
      </div>
      <div class="table-wrap">
        <table class="dtable">
          <thead>
            <tr><th>仓库</th><th>Tag</th><th>镜像 ID</th><th class="num">大小</th><th>创建</th><th>状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="image in filteredImages" :key="`${image.id}-${image.tag}`">
              <td class="mono">{{ image.repository }}</td>
              <td class="mono">{{ image.tag }}</td>
              <td class="mono">{{ image.id }}</td>
              <td class="num mono">{{ image.size || "—" }}</td>
              <td>{{ image.created || "—" }}</td>
              <td>
                <span class="pill" :class="image.in_use ? 'good' : ''">
                  {{ image.in_use ? "使用中" : image.dangling ? "悬空" : "未使用" }}
                </span>
              </td>
            </tr>
            <tr v-if="!filteredImages.length"><td colspan="6" class="muted">没有匹配的镜像</td></tr>
          </tbody>
        </table>
      </div>
      <p class="note">
        {{ usedImages }} / {{ images.length }} 个镜像正在被容器使用；悬空镜像指没有仓库或标签的中间层。
      </p>
    </section>
  </div>
</template>

<script setup>
import { computed, inject, ref, watch } from "vue";

const dash = inject("dash");
const rows = computed(() => dash.groupData("containers") || []);
const images = computed(() => dash.groupData("docker_images") || []);

const stateFilter = ref("all");
const query = ref("");
const page = ref(1);
const pageSize = 10;

const isBad = (item) =>
  item.health === "unhealthy" || ["dead", "restarting"].includes(item.state);

const running = computed(() => rows.value.filter((item) => item.state === "running").length);
const unhealthy = computed(() => rows.value.filter(isBad).length);
const usedImages = computed(() => images.value.filter((image) => image.in_use).length);
const unusedImages = computed(() => images.value.length - usedImages.value);

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return rows.value.filter((item) => {
    if (stateFilter.value === "running" && item.state !== "running") return false;
    if (stateFilter.value === "stopped" && item.state === "running") return false;
    if (stateFilter.value === "bad" && !isBad(item)) return false;
    if (needle && !item.name.toLowerCase().includes(needle) && !item.image.toLowerCase().includes(needle))
      return false;
    return true;
  });
});

const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)));
const paged = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
);

watch([stateFilter, query], () => {
  page.value = 1;
});
watch(pageCount, (count) => {
  if (page.value > count) page.value = count;
});

const imageFilter = ref("all");
const filteredImages = computed(() => {
  if (imageFilter.value === "used") return images.value.filter((image) => image.in_use);
  if (imageFilter.value === "unused") return images.value.filter((image) => !image.in_use);
  return images.value;
});

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
    ] || item.state || "状态未知"
  );
};

const tone = (item) =>
  isBad(item) ? "bad" : item.state === "running" ? "good" : "muted";
</script>
