import {
  Pause,
  Calendar,
  ArrowRight,
  Bot,
  ClipboardClock,
  BotOff,
  Play,
} from "lucide-react";
import { useState, type MouseEvent } from "react";

import { parseCronExpression, getFrequencyLabel } from "./schedule-utils";
import { scheduleApi, type ScheduleRecord } from "@/api";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import { useTranslation } from "@/i18n/useI18n";

interface ScheduleCardProps {
  schedule: ScheduleRecord;
  onClick: () => void;
}

export function ScheduleCard({ schedule, onClick }: ScheduleCardProps) {
  const { t } = useTranslation();
  const { data } = schedule;
  const parsed = parseCronExpression(data.cron_expression, data.started_at);
  const [running, setRunning] = useState(false);
  const runNow = async (event: MouseEvent) => {
    event.stopPropagation();
    setRunning(true);
    try {
      await scheduleApi.runNow(schedule.id);
      toast.success("已开始执行，结果将显示为新的会话。");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "立即执行失败");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Item
      className="cursor-pointer hover:shadow-md"
      variant="outline"
      onClick={onClick}
    >
      <ItemMedia variant="icon">
        {data.enabled ? <Bot /> : <BotOff />}
      </ItemMedia>
      <ItemContent>
        <ItemTitle className="font-[550] truncate max-w-full">
          {data.name}
        </ItemTitle>
        <ItemDescription className="flex gap-x-2 items-center text-xs truncate overflow-hidden">
          {!data.enabled && (
            <Badge variant="secondary" className="gap-1">
              <Pause className="h-3 w-3" />
              {t("common.disabled")}
            </Badge>
          )}
          <Badge variant="link" className="pl-0">
            <Calendar data-icon="inline-start" />
            {new Date(data.started_at).toLocaleDateString()}
            {data.ended_at && (
              <div className="flex items-center gap-1">
                <ArrowRight className="size-3 text-muted-foreground" />
                {new Date(data.ended_at).toLocaleDateString()}
              </div>
            )}
            <div>{parsed.time}</div>
          </Badge>
          <Badge variant="link">
            <ClipboardClock data-icon="inline-start" />
            {getFrequencyLabel(parsed, t)}
          </Badge>
        </ItemDescription>
      </ItemContent>
      <Button
        size="sm"
        className="bg-emerald-600 text-white hover:bg-emerald-700 dark:bg-emerald-600 dark:hover:bg-emerald-700"
        disabled={running || !data.enabled}
        onClick={runNow}
      >
        <Play className="size-3.5" />
        {running ? "执行中…" : "立即执行"}
      </Button>
    </Item>
  );
}
