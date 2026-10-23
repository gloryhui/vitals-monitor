<template>
  <footer class="footer">
    <span>Vitals · 轻量监控 · 只读展示 · {{ hostname }}</span>
    <details>
      <summary>数据更新说明</summary>
      <p>
        CPU / 内存 / 网络流量 / 磁盘读写：1 秒；温度 / 进程排行：5 秒；容器 / 服务检查：15
        秒；分区容量 / 网络信息：30 秒；磁盘健康：1 分钟；Docker 空间：5 分钟；系统与硬件：1
        小时。页面隐藏时暂停请求。采样压缩存入 SQLite，保留
        {{ dash.state.retentionDays }} 天后自动清理；30/90 天范围使用小时聚合。事件每 5 秒查询，按持续异常和恢复转换记录。
      </p>
    </details>
  </footer>
</template>

<script setup>
import { computed, inject } from "vue";

const dash = inject("dash");
const hostname = computed(
  () => dash.groupData("system")?.hostname || dash.state.fast?.hostname || "本机",
);
</script>
