export const finite = (value) => typeof value === "number" && Number.isFinite(value);

export const num = (value, digits = 1) => (finite(value) ? value.toFixed(digits) : "—");

export function fmtBytes(value, digits = 1) {
  if (!finite(value)) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let index = 0;
  while (Math.abs(value) >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : digits)} ${units[index]}`;
}

export const fmtRate = (value) => (finite(value) ? `${fmtBytes(value)}/s` : "—");

export const fmtTime = (value) =>
  new Date(value).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

export function duration(seconds) {
  if (!finite(seconds)) return "—";
  const days = Math.floor(seconds / 86400);
  return `${days ? `${days} 天 ` : ""}${Math.floor((seconds % 86400) / 3600)} 小时 ${Math.floor(
    (seconds % 3600) / 60,
  )} 分钟`;
}

export function eventDuration(seconds) {
  if (!finite(seconds)) return "";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
  return duration(seconds);
}

export const rangeLabel = (minutes) =>
  ({
    10: "10 分钟",
    30: "30 分钟",
    60: "1 小时",
    360: "6 小时",
    1440: "24 小时",
    10080: "7 天",
    43200: "30 天",
    129600: "90 天",
  })[minutes] || `${minutes} 分钟`;

export const RANGE_OPTIONS = [10, 30, 60, 360, 1440, 10080, 43200, 129600];
