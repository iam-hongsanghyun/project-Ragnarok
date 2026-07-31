/**
 * ECharts module registration — single source of truth for which renderers,
 * chart types, and components ship in the bundle (tree-shaken via
 * `echarts/core`). Every chart imports `echarts` from here, never from
 * 'echarts' directly, so the registration list stays complete.
 *
 * Renderer: SVG, deliberately. The Excel export pipeline
 * (lib/export/chart.ts) serialises the on-screen `<svg>` to a PNG; the SVG
 * renderer keeps that working unchanged — and unlike the old hand-rolled
 * charts, ECharts inlines every style attribute, so the exported image no
 * longer loses class-based styling.
 */
import * as echarts from 'echarts/core';
import {
  BarChart,
  CustomChart,
  LineChart,
  PieChart,
  ScatterChart,
} from 'echarts/charts';
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';

echarts.use([
  BarChart,
  CustomChart,
  LineChart,
  PieChart,
  ScatterChart,
  DataZoomComponent, // inside (wheel/drag) + slider zoom on time/category axes
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  ToolboxComponent, // dataZoom toggle, restore, saveAsImage
  TooltipComponent,
  SVGRenderer,
]);

export { echarts };
export type { EChartsType } from 'echarts/core';
