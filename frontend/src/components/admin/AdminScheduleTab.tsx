import { useEffect, useState } from "react";
import { settingsApi } from "@/api/endpoints";
import { Card } from "@/components/ui/card";
import { Alert } from "@/components/ui/feedback";
import { Field, FieldDescription, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useAutoSave } from "@/hooks/useAutoSave";

interface SchedulePair {
  schedule: Record<string, unknown>;
  trends: Record<string, unknown>;
}

const TIME_PATTERN = /^([01]?\d|2[0-3]):[0-5]\d$/;

interface AdminScheduleTabProps {
  onDirtyChange?: (dirty: boolean) => void;
}

export function AdminScheduleTab({ onDirtyChange }: AdminScheduleTabProps = {}) {
  const [schedule, setSchedule] = useState<Record<string, unknown>>({});
  const [trends, setTrends] = useState<Record<string, unknown>>({});
  const [intervalDraft, setIntervalDraft] = useState("30");
  const [retentionDraft, setRetentionDraft] = useState("30");
  const [topNDraft, setTopNDraft] = useState("10");
  const [error, setError] = useState("");

  const scheduleAuto = useAutoSave<SchedulePair>({
    delayMs: 550,
    validate: ({ schedule: s, trends: t }) => {
      const timeText = String(s.daily_report_time ?? "22:00").trim();
      if (!TIME_PATTERN.test(timeText)) {
        return "每日报告时间需为 HH:MM 格式（如 22:00）";
      }
      const rawInterval = s.crawl_interval_minutes;
      if (rawInterval === "" || rawInterval === null || rawInterval === undefined) {
        return "请填写自动更新间隔（不能少于 5 分钟）";
      }
      const interval = Number(rawInterval);
      if (!Number.isFinite(interval) || interval < 5) {
        return "自动更新间隔不能少于 5 分钟";
      }
      const rawRetention = s.retention_days;
      if (rawRetention === "" || rawRetention === null || rawRetention === undefined) {
        return "请填写原始新闻保留天数（填 0 表示永久保留）";
      }
      const retention = Number(rawRetention);
      if (!Number.isFinite(retention) || retention < 0) {
        return "原始新闻保留天数不能为负数（填 0 表示永久保留）";
      }
      const rawTopN = t.daily_top_n;
      if (rawTopN === "" || rawTopN === null || rawTopN === undefined) {
        return "请填写趋势图每日 Top N 事件数（至少 1）";
      }
      const topN = Number(rawTopN);
      if (!Number.isFinite(topN) || topN < 1) {
        return "趋势图每日 Top N 事件数需大于等于 1";
      }
      return null;
    },
    onSave: async (payload) => {
      await Promise.all([
        settingsApi.updateSection("schedule", payload.schedule),
        settingsApi.updateSection("trends", payload.trends),
      ]);
    },
    keepaliveFlush: (payload) => {
      settingsApi.keepaliveUpdateSection("schedule", payload.schedule);
      settingsApi.keepaliveUpdateSection("trends", payload.trends);
    },
  });

  useEffect(() => {
    Promise.all([settingsApi.getSection("schedule"), settingsApi.getSection("trends")])
      .then(([s, t]) => {
        setSchedule(s.payload);
        setTrends(t.payload);
        setIntervalDraft(String(s.payload.crawl_interval_minutes ?? 30));
        setRetentionDraft(String(s.payload.retention_days ?? 30));
        setTopNDraft(String(t.payload.daily_top_n ?? 10));
        scheduleAuto.hydrate({ schedule: s.payload, trends: t.payload });
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载系统调度配置失败"));
    // Run once on initial mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    onDirtyChange?.(scheduleAuto.dirty);
  }, [scheduleAuto.dirty, onDirtyChange]);

  const updateSchedule = (nextSchedule: Record<string, unknown>, immediate = false) => {
    setSchedule(nextSchedule);
    scheduleAuto.queueSave({ schedule: nextSchedule, trends }, { immediate });
  };

  const updateTrends = (nextTrends: Record<string, unknown>, immediate = false) => {
    setTrends(nextTrends);
    scheduleAuto.queueSave({ schedule, trends: nextTrends }, { immediate });
  };

  return (
    <div className="flex flex-col gap-5">
      {(error || scheduleAuto.error) && (
        <Alert variant="destructive">{error || scheduleAuto.error}</Alert>
      )}

      <Card className="p-4 sm:p-5">
        <div className="mb-3">
          <h3 className="text-base font-semibold">全站定时采集与趋势参数</h3>
          <p className="text-sm text-muted-foreground">修改后自动实时热更新后台定时任务，无需重启服务</p>
        </div>

        <FieldGroup>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel>自动更新间隔（分钟）</FieldLabel>
              <FieldDescription>最低 5 分钟，建议设为 30 分钟；每次采集后会自动向开启推送的成员分发增量通知</FieldDescription>
              <Input
                type="text"
                inputMode="numeric"
                value={intervalDraft}
                onChange={(e) => {
                  const val = e.target.value;
                  setIntervalDraft(val);
                  const trimmed = val.trim();
                  updateSchedule({
                    ...schedule,
                    crawl_interval_minutes: trimmed === "" ? "" : Number(trimmed),
                  });
                }}
              />
            </Field>
            <Field>
              <FieldLabel>每日总体 AI 报告触发时间 (HH:MM)</FieldLabel>
              <FieldDescription>每天按此时刻自动汇总生成全天热点报告</FieldDescription>
              <Input
                value={String(schedule.daily_report_time ?? "22:00")}
                onChange={(e) => updateSchedule({ ...schedule, daily_report_time: e.target.value })}
                placeholder="例如：22:00"
              />
            </Field>
            <Field>
              <FieldLabel>本地新闻保留天数</FieldLabel>
              <FieldDescription>填 0 表示永久保留，建议保留 30 天</FieldDescription>
              <Input
                type="text"
                inputMode="numeric"
                value={retentionDraft}
                onChange={(e) => {
                  const val = e.target.value;
                  setRetentionDraft(val);
                  const trimmed = val.trim();
                  updateSchedule({
                    ...schedule,
                    retention_days: trimmed === "" ? "" : Number(trimmed),
                  });
                }}
              />
            </Field>
            <Field>
              <FieldLabel>趋势图默认每日展示条数 (Top N)</FieldLabel>
              <FieldDescription>控制跨天趋势图中每天重点连线的事件个数</FieldDescription>
              <Input
                type="text"
                inputMode="numeric"
                value={topNDraft}
                onChange={(e) => {
                  const val = e.target.value;
                  setTopNDraft(val);
                  const trimmed = val.trim();
                  updateTrends({
                    ...trends,
                    daily_top_n: trimmed === "" ? "" : Number(trimmed),
                  });
                }}
              />
            </Field>
          </div>
        </FieldGroup>
      </Card>
    </div>
  );
}
