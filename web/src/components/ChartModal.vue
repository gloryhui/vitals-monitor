<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-card" role="dialog" aria-modal="true" :aria-label="chart.title">
      <div class="modal-head">
        <h3>{{ chart.title }}</h3>
        <div class="modal-tools">
          <button ref="closeButton" class="btn" type="button" @click="$emit('close')">
            关闭
          </button>
        </div>
      </div>
      <div class="modal-body">
        <ChartBlock
          :chart-id="chart.id"
          :keys="chart.keys"
          :max="chart.max"
          :format="chart.format"
          :labels="chart.labels"
          large
          :zoomable="false"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import ChartBlock from "./ChartBlock.vue";

defineProps({
  chart: { type: Object, required: true },
});
const emit = defineEmits(["close"]);
const closeButton = ref(null);

const onKeydown = (event) => {
  if (event.key === "Escape") emit("close");
};

onMounted(() => {
  document.body.classList.add("modal-open");
  document.addEventListener("keydown", onKeydown);
  closeButton.value?.focus();
});

onBeforeUnmount(() => {
  document.body.classList.remove("modal-open");
  document.removeEventListener("keydown", onKeydown);
});
</script>

<style scoped>
.modal-body {
  display: flex;
  flex-direction: column;
}
.modal-body :deep(.chart-head) {
  flex: none;
}
.modal-body :deep(.chart-box) {
  flex: 1;
  height: auto;
  min-height: 0;
}
</style>
