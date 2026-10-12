export { formatNumber, formatPercent, formatTime } from "@vtrs/core";
export type { AreaResult } from "@vtrs/core";

export interface TimelinePointLike {
  at: string;
  newly_reported: number;
  cumulative: number;
}
