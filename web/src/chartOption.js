import { finite } from "./format";

const withAlpha = (color, alpha) => {
  if (!color || !color.startsWith("#")) return color;
  const hex = color.length === 4
    ? color.slice(1).split("").map((c) => c + c).join("")
    : color.slice(1);
  const value = Math.round(Math.min(1, Math.max(0, alpha)) * 255)
    .toString(16)
    .padStart(2, "0");
  return `#${hex}${value}`;
};

export function buildChartOption({
  points,
  keys,
  labels,
  colors,
  max,
  format,
  interval,
  large = false,
  muted,
  line,
  surface,
  text,
}) {
  const series = keys.map((key, index) => ({
    name: labels[key] || key,
    type: "line",
    showSymbol: false,
    symbol: "circle",
    symbolSize: large ? 6 : 4,
    smooth: 0.15,
    connectNulls: false,
    lineStyle: { width: large ? 2.2 : 1.7, color: colors[index] },
    itemStyle: { color: colors[index] },
    emphasis: { focus: "series" },
    areaStyle: {
      color: {
        type: "linear",
        x: 0,
        y: 0,
        x2: 0,
        y2: 1,
        colorStops: [
          { offset: 0, color: withAlpha(colors[index], 0.24) },
          { offset: 1, color: withAlpha(colors[index], 0.01) },
        ],
      },
    },
    data: points.map((point) => [
      Math.round(point.t * 1000),
      finite(point[key]) ? point[key] : null,
    ]),
  }));

  return {
    animation: false,
    textStyle: { fontFamily: "var(--sans)" },
    grid: {
      left: large ? 74 : 54,
      right: large ? 26 : 14,
      top: large ? 26 : 12,
      bottom: large ? 40 : 26,
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: surface,
      borderColor: line,
      borderWidth: 1,
      padding: [8, 11],
      textStyle: { color: text, fontSize: 12 },
      axisPointer: {
        type: "cross",
        lineStyle: { color: muted, type: "dashed", width: 1 },
        crossStyle: { color: muted, type: "dashed", width: 1 },
      },
      formatter: (params) => {
        if (!params || !params.length) return "";
        const stamp = new Date(params[0].value[0]).toLocaleString("zh-CN", {
          hour12: false,
          month: "numeric",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        });
        const rows = params
          .filter((item) => item.value[1] !== null && item.value[1] !== undefined)
          .map(
            (item) =>
              `${item.marker}${item.seriesName} <b style="float:right;margin-left:18px">${format(item.value[1])}</b>`,
          );
        return `<div style="font-size:11px;opacity:.75;margin-bottom:4px">${stamp}</div>${rows.join("<br/>")}`;
      },
    },
    xAxis: {
      type: "time",
      boundaryGap: false,
      axisLine: { lineStyle: { color: line } },
      axisTick: { show: false },
      axisLabel: {
        color: muted,
        fontSize: large ? 11 : 10,
        hideOverlap: true,
        formatter: (value) => {
          const date = new Date(value);
          const month = date.getMonth() + 1;
          const day = date.getDate();
          const hour = String(date.getHours()).padStart(2, "0");
          const minute = String(date.getMinutes()).padStart(2, "0");
          return interval >= 3600 ? `${month}/${day}` : `${hour}:${minute}`;
        },
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: max ?? undefined,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: muted,
        fontSize: large ? 11 : 10,
        formatter: (value) => format(value),
      },
      splitLine: { lineStyle: { color: line, type: "dashed" } },
    },
    series,
  };
}
