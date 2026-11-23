import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import type { TrendSeriesDTO } from "@/api/types";
import {
  buildUniqueSeriesName,
  computeAdaptiveYBounds,
  computeCenteredXAxis,
  computeSingleDayLayout,
  diffDaysUtc,
  escapeHtml,
  getEventColor,
  shiftIsoDateUtc,
  truncateLabel,
} from "./trendChartUtils";

/** Props for the interactive centered trend chart component. */
export interface TrendChartProps {
  dates: string[];
  series: TrendSeriesDTO[];
  onSelectPoint: (eventId: number, date: string) => void;
  domainNameMap?: Record<string, string>;
}

interface ChartPointPayload {
  value: [number, number];
  eventId: number;
  date: string;
  hotIndex: number;
  canonicalTitle: string;
  domain: string;
  dailyRank: number;
  platformCount: number;
  velocity: number;
  dx: number;
  symbolSize?: number;
  label?: Record<string, unknown>;
}

function formatTooltipHtml(
  d: ChartPointPayload,
  domainNameMap?: Record<string, string>,
): string {
  const domainLabel = domainNameMap?.[d.domain] || d.domain;
  return [
    `<div style="font-weight:600;margin-bottom:4px;">${escapeHtml(d.canonicalTitle)}</div>`,
    `<div>日期：${escapeHtml(d.date)} · 领域：${escapeHtml(domainLabel)}</div>`,
    `<div>综合关注度：<b>${d.hotIndex}</b> · 当日第 #${d.dailyRank} 名</div>`,
    `<div>覆盖平台：${d.platformCount} 个</div>`,
    `<div style="color:#1d4ed8;margin-top:4px;">点击查看关联报道与报告</div>`,
  ].join("");
}

function buildTodayGuideSeries(anchorDate: string, axisLimit: number): echarts.SeriesOption {
  const shortToday = anchorDate ? anchorDate.slice(5) : "";
  return {
    name: "__today_guide__",
    type: "scatter",
    silent: true,
    tooltip: { show: false },
    data: [],
    z: 1,
    markArea: {
      silent: true,
      itemStyle: { color: "rgba(248, 250, 252, 0.72)" },
      data: [[{ xAxis: 0 }, { xAxis: axisLimit }]],
    },
    markLine: {
      silent: true,
      symbol: ["none", "none"],
      lineStyle: { color: "#93c5fd", width: 1.5, type: "dashed" },
      label: {
        show: true,
        position: "end",
        rotate: 0,
        distance: 8,
        formatter: shortToday ? `今日 ${shortToday}` : "今日",
        color: "#1d4ed8",
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: "#eff6ff",
        borderColor: "#bfdbfe",
        borderWidth: 1,
        borderRadius: 4,
        padding: [3, 8],
      },
      data: [{ xAxis: 0 }],
    },
  };
}

function buildMultiDaySeriesOption(
  item: TrendSeriesDTO,
  seriesName: string,
  color: string,
  anchorDate: string,
  isCompact: boolean,
): echarts.SeriesOption {
  const sortedPoints = [...item.points].sort((a, b) => a.date.localeCompare(b.date));
  const data: ChartPointPayload[] = sortedPoints.map((pt) => ({
    value: [anchorDate ? diffDaysUtc(pt.date, anchorDate) : 0, pt.hot_index],
    eventId: item.event_id,
    date: pt.date,
    hotIndex: pt.hot_index,
    canonicalTitle: item.canonical_title,
    domain: item.domain,
    dailyRank: pt.daily_rank,
    platformCount: pt.platform_count,
    velocity: pt.velocity,
    dx: 0,
  }));

  return {
    name: seriesName,
    type: "line",
    smooth: 0.25,
    connectNulls: true,
    symbol: "circle",
    symbolSize: isCompact ? 9 : 8,
    lineStyle: { width: 2.5, color },
    itemStyle: { color, borderColor: "#ffffff", borderWidth: 2 },
    emphasis: { focus: "series" },
    z: 3,
    data,
  };
}

function buildSingleDaySeriesOption(
  item: TrendSeriesDTO,
  seriesName: string,
  color: string,
  anchorDate: string,
  offsets: Map<string, number>,
  showInlineLabel: boolean,
  isCompact: boolean,
): echarts.SeriesOption {
  const data: ChartPointPayload[] = item.points.map((pt) => {
    const dayOffset = anchorDate ? diffDaysUtc(pt.date, anchorDate) : 0;
    const dx = offsets.get(`${item.event_id}:${pt.date}`) ?? 0;
    return {
      value: [dayOffset + dx, pt.hot_index],
      eventId: item.event_id,
      date: pt.date,
      hotIndex: pt.hot_index,
      canonicalTitle: item.canonical_title,
      domain: item.domain,
      dailyRank: pt.daily_rank,
      platformCount: pt.platform_count,
      velocity: pt.velocity,
      dx,
      symbolSize: Math.max(isCompact ? 13 : 12, Math.min(20, 9 + pt.hot_index * 0.12)),
      label: showInlineLabel
        ? {
            show: true,
            position: dx < 0 ? "left" : "right",
            distance: 8,
            formatter: () => truncateLabel(item.canonical_title, 10),
            color: "#27272a",
            fontSize: 11,
            backgroundColor: "rgba(255, 255, 255, 0.88)",
            borderRadius: 3,
            padding: [1, 4],
          }
        : undefined,
    };
  });

  return {
    name: seriesName,
    type: "scatter",
    itemStyle: {
      color,
      borderColor: "#ffffff",
      borderWidth: 2,
      shadowBlur: 6,
      shadowColor: "rgba(15, 23, 42, 0.14)",
    },
    emphasis: { focus: "series", scale: 1.25 },
    labelLayout: { hideOverlap: true },
    z: 4,
    data,
  };
}

function buildXAxisFormatter(anchorDate: string) {
  return (val: number) => {
    const rounded = Math.round(val);
    if (Math.abs(val - rounded) > 1e-6 || !anchorDate) return "";
    const shortDate = shiftIsoDateUtc(anchorDate, rounded).slice(5);
    if (rounded === 0) return `{today|今日 ${shortDate}}`;
    if (rounded < 0) return `{past|${shortDate}}`;
    return `{future|${shortDate}}`;
  };
}

function buildChartOption(
  dates: string[],
  series: TrendSeriesDTO[],
  isCompact: boolean,
  domainNameMap?: Record<string, string>,
): echarts.EChartsOption {
  const { anchorDate, axisLimit, tickStep, maxPastData } = computeCenteredXAxis({
    dates,
    series,
    isCompact,
  });
  const { yMin, yMax } = computeAdaptiveYBounds(series);
  const offsets = computeSingleDayLayout({
    series,
    anchorDate,
    maxPastData,
    yMin,
    yMax,
    isCompact,
  });

  const usedNames = new Set<string>();
  const eventSeriesNames: string[] = [];
  const showInlineLabels = !isCompact && maxPastData === 0 && series.length <= 12;

  const eventSeries = series.map((item, idx) => {
    const domainLabel = domainNameMap?.[item.domain] || item.domain;
    const seriesName = buildUniqueSeriesName(item.canonical_title, domainLabel, usedNames);
    eventSeriesNames.push(seriesName);
    const color = getEventColor(idx);
    if (item.is_multi_day) {
      return buildMultiDaySeriesOption(item, seriesName, color, anchorDate, isCompact);
    }
    return buildSingleDaySeriesOption(
      item,
      seriesName,
      color,
      anchorDate,
      offsets,
      showInlineLabels,
      isCompact,
    );
  });

  return {
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: "#ffffff",
      borderColor: "#e4e4e7",
      textStyle: { color: "#18181b", fontSize: 12 },
      extraCssText: "max-width: 260px; white-space: normal;",
      formatter: (params: unknown) => {
        const data = (params as { data?: ChartPointPayload }).data;
        return data ? formatTooltipHtml(data, domainNameMap) : "";
      },
    },
    legend: {
      type: "scroll",
      bottom: 0,
      icon: "circle",
      itemWidth: 10,
      itemHeight: 10,
      data: eventSeriesNames,
      textStyle: { fontSize: 11, color: "#52525b" },
      formatter: (name: string) => truncateLabel(name, isCompact ? 10 : 14),
    },
    grid: isCompact
      ? { left: 42, right: 16, top: 48, bottom: 56 }
      : { left: 54, right: 28, top: 52, bottom: 60 },
    xAxis: {
      type: "value",
      min: -axisLimit,
      max: axisLimit,
      interval: tickStep,
      axisLine: { lineStyle: { color: "#d4d4d8" } },
      axisTick: { lineStyle: { color: "#d4d4d8" } },
      splitLine: { show: true, lineStyle: { color: "#f4f4f5", type: "dashed" } },
      axisLabel: {
        formatter: buildXAxisFormatter(anchorDate),
        rich: {
          today: { color: "#1d4ed8", fontWeight: 700, fontSize: isCompact ? 10 : 11 },
          past: { color: "#52525b", fontSize: isCompact ? 10 : 11 },
          future: { color: "#a1a1aa", fontSize: isCompact ? 10 : 11 },
        },
      },
    },
    yAxis: {
      type: "value",
      name: "综合关注度",
      nameGap: 16,
      min: yMin,
      max: yMax,
      axisLine: { show: false, onZero: false },
      axisTick: { show: false },
      nameTextStyle: {
        color: "#52525b",
        fontSize: 11,
        align: "left",
        padding: [0, 0, 0, -24],
      },
      splitLine: { lineStyle: { color: "#f1f5f9" } },
      axisLabel: { color: "#52525b", fontSize: 11 },
    },
    series: [buildTodayGuideSeries(anchorDate, axisLimit), ...eventSeries],
  };
}

/** Interactive today-centered trend chart distinguishing single-day and multi-day events by color. */
export function TrendChart({ dates, series, onSelectPoint, domainNameMap }: TrendChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const [isCompact, setIsCompact] = useState(false);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setIsCompact(el.clientWidth < 520);
    const chart = echarts.init(el);
    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      setIsCompact(el.clientWidth < 520);
      chart.resize();
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    chart.setOption(buildChartOption(dates, series, isCompact, domainNameMap), true);
    chart.off("click");
    chart.on("click", (params: unknown) => {
      const data = (params as { data?: ChartPointPayload }).data;
      if (data?.eventId && data?.date) {
        onSelectPoint(data.eventId, data.date);
      }
    });
  }, [dates, series, onSelectPoint, isCompact, domainNameMap]);

  return <div ref={containerRef} className="h-[340px] sm:h-[460px] w-full" />;
}
