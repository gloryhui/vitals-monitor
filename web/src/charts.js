import { fmtBytes } from "./format";

const percent = (value) => `${Math.round(value)}%`;
const celsius = (value) => `${Math.round(value)}°C`;
const rate = (value) => `${fmtBytes(value, 0)}/s`;

export const CHARTS = {
  chartUsage: {
    id: "chartUsage",
    title: "CPU 使用率",
    keys: ["cpu"],
    max: 100,
    format: percent,
    labels: { cpu: "CPU" },
  },
  chartMemory: {
    id: "chartMemory",
    title: "内存使用率",
    keys: ["mem"],
    max: 100,
    format: percent,
    labels: { mem: "内存" },
  },
  chartTemp: {
    id: "chartTemp",
    title: "温度",
    keys: ["temp", "ccd", "nvme", "nvme_s1", "nvme_s2", "hdd"],
    max: null,
    format: celsius,
    labels: {
      temp: "CPU",
      ccd: "CCD",
      nvme: "NVMe",
      nvme_s1: "探头 1",
      nvme_s2: "探头 2",
      hdd: "硬盘",
    },
  },
  chartDisk: {
    id: "chartDisk",
    title: "磁盘读写",
    keys: ["dr", "dw"],
    max: null,
    format: rate,
    labels: { dr: "读取", dw: "写入" },
  },
  chartNetwork: {
    id: "chartNetwork",
    title: "网络流量",
    keys: ["rx", "tx"],
    max: null,
    format: rate,
    labels: { rx: "接收", tx: "发送" },
  },
};
