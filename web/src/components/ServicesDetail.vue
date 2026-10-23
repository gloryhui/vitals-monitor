<template>
  <div class="detail-grid">
    <section class="detail-section">
      <div class="detail-stats">
        <div><span>检查项</span><b>{{ rows.length }}</b></div>
        <div><span>正常</span><b>{{ okCount }}</b></div>
        <div><span>异常</span><b>{{ rows.length - okCount }}</b></div>
        <div><span>状态</span><b>{{ statusText }}</b></div>
      </div>
    </section>

    <section class="detail-section">
      <h3>全部检查</h3>
      <table class="dtable">
        <thead>
          <tr><th>名称</th><th>类型</th><th>目标</th><th>结果</th><th class="num">延迟</th><th class="num">连续失败</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in rows" :key="item.id">
            <td>{{ item.name }}</td>
            <td>{{ item.type }}</td>
            <td class="mono">{{ item.target || "—" }}</td>
            <td :class="item.ok ? 'good' : 'bad'">{{ item.detail }}</td>
            <td class="num mono">{{ item.latency_ms }} ms</td>
            <td class="num mono">{{ item.consecutive_failures || 0 }}</td>
          </tr>
          <tr v-if="!rows.length"><td colspan="6" class="muted">暂无服务检查配置</td></tr>
        </tbody>
      </table>
      <p class="note">每 15 秒检查一次；连续失败和连续成功达到阈值后才会记录事件。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, inject } from "vue";

const dash = inject("dash");
const rows = computed(() => dash.groupData("services") || []);
const okCount = computed(() => rows.value.filter((item) => item.ok).length);
const statusText = computed(() => dash.groupStatus("services"));
</script>
