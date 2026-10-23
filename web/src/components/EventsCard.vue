<template>
  <article class="card">
    <div class="card-head">
      <h2>异常与恢复记录 <span class="pill">{{ countText }}</span></h2>
      <span class="pill" :class="{ warn: dash.state.eventError }">{{ updatedText }}</span>
    </div>
    <div class="card-body">
      <div class="event-list">
        <div v-for="item in dash.state.events" :key="item.id" class="event-row">
          <span class="event-phase" :class="phaseTone(item)">
            {{ item.phase === "recovered" ? "恢复" : "异常" }}
          </span>
          <div class="event-content">
            <div class="event-message">{{ item.message }}</div>
            <div class="event-meta">
              {{ moment(item.occurred_at) }}
              <template v-if="item.duration_seconds != null"> · 持续 {{ eventDuration(item.duration_seconds) }}</template>
            </div>
          </div>
        </div>
        <div v-if="!dash.state.events.length" class="note">
          暂无异常或恢复记录。持续异常和恢复确认后会自动记录。
        </div>
      </div>
      <button
        v-if="dash.state.eventCursor !== null"
        class="btn"
        type="button"
        :disabled="dash.state.loadingOlder"
        @click="dash.loadOlderEvents()"
      >
        查看更早记录
      </button>
      <p class="note">
        持续异常只记录一次，恢复后单独记录。事件保留 {{ dash.state.retentionDays }} 天。
      </p>
    </div>
  </article>
</template>

<script setup>
import { computed, inject } from "vue";
import { eventDuration, fmtTime } from "../format";

const dash = inject("dash");
const countText = computed(() =>
  dash.state.events.length ? `${dash.state.events.length} 条已载入` : "暂无记录",
);
const updatedText = computed(() =>
  dash.state.eventError || !dash.state.eventGeneratedAt
    ? "无法更新，重试中"
    : `${fmtTime(dash.state.eventGeneratedAt)} 更新`,
);
const phaseTone = (item) =>
  item.phase === "recovered" ? "good" : item.severity === "critical" ? "bad" : "warn";
const moment = (seconds) =>
  new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false });
</script>
