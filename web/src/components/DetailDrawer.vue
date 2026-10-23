<template>
  <div class="detail-backdrop" @click.self="$emit('close')">
    <aside class="detail-panel" role="dialog" aria-modal="true" :aria-label="title">
      <header class="detail-head">
        <h2>{{ title }}</h2>
        <button ref="closeButton" class="btn" type="button" @click="$emit('close')">关闭</button>
      </header>
      <div class="detail-body">
        <component :is="component" />
      </div>
    </aside>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import CpuDetail from "./CpuDetail.vue";
import MemoryDetail from "./MemoryDetail.vue";
import TemperatureDetail from "./TemperatureDetail.vue";
import StorageDetail from "./StorageDetail.vue";
import NetworkDetail from "./NetworkDetail.vue";
import ContainersDetail from "./ContainersDetail.vue";
import ServicesDetail from "./ServicesDetail.vue";

const props = defineProps({ detail: { type: String, required: true } });
const emit = defineEmits(["close"]);

const COMPONENTS = {
  cpu: CpuDetail,
  memory: MemoryDetail,
  temperature: TemperatureDetail,
  storage: StorageDetail,
  network: NetworkDetail,
  containers: ContainersDetail,
  services: ServicesDetail,
};
const TITLES = {
  cpu: "CPU 详情",
  memory: "内存详情",
  temperature: "温度详情",
  storage: "存储详情",
  network: "网络详情",
  containers: "容器详情",
  services: "服务检查详情",
};

const component = computed(() => COMPONENTS[props.detail] || CpuDetail);
const title = computed(() => TITLES[props.detail] || "详情");
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
