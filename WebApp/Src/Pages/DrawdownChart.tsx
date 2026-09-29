import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { DataZoomComponent, GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { AssetRiskReport } from "../Api/Risk";

echarts.use([LineChart, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer]);

export function DrawdownChart({ curve }: { curve: AssetRiskReport["drawdown"]["curve"] }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current || curve.length === 0) return;
    const chart = echarts.init(container.current);
    chart.setOption({
      animation: false,
      tooltip: { trigger: "axis", valueFormatter: (value: unknown) =>
        typeof value === "number" ? `${value.toFixed(2)}%` : String(value) },
      grid: { left: 60, right: 24, top: 20, bottom: 55 },
      xAxis: { type: "category", data: curve.map((point) => point.trade_date), name: "交易日期" },
      yAxis: { type: "value", name: "回撤 %", axisLabel: { formatter: "{value}%" } },
      dataZoom: [{ type: "inside" }, { type: "slider", bottom: 8 }],
      series: [{ name: "回撤", type: "line", showSymbol: false, smooth: false,
        data: curve.map((point) => point.drawdown * 100), areaStyle: { opacity: 0.12 } }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [curve]);

  return <div className="drawdown-chart" ref={container} role="img" aria-label="按交易日期展示的历史回撤曲线" />;
}
