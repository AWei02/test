import { format } from "date-fns";
import {
  ChevronDownIcon,
  CircleAlert,
  Loader2,
  PlusCircle,
  Upload,
} from "lucide-react";
import * as React from "react";

import type {
  ChatModelConfig,
  PermissionMode,
  ScheduleRecord,
  UpdateScheduleRequest,
} from "@/api";
import { AgentSelect } from "@/components/select/AgentSelect";
import { LlmSelect } from "@/components/select/LlmSelect";
import { PermissionModeSelect } from "@/components/select/PermissionModeSelect";
import { TimezoneSelect } from "@/components/select/TimezoneSelect";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAgents } from "@/hooks/useAgents";
import { useProjects } from "@/hooks/useProjects";
import { useSchedules } from "@/hooks/useSchedules";
import { useTranslation } from "@/i18n/useI18n";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: () => void;
  schedule?: ScheduleRecord | null;
  onUpdated?: (
    scheduleId: string,
    body: UpdateScheduleRequest,
  ) => Promise<unknown>;
}

type FreqType = "once" | "daily" | "weekly" | "monthly";

function getDefaultForm() {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  return {
    name: "",
    description: "",
    freq: "daily" as FreqType,
    date: now,
    time: `${hh}:${mm}`,
    endDate: undefined as Date | undefined,
    agentId: "",
    projectId: "",
    chatModelConfig: null as ChatModelConfig | null,
    permissionMode: "dont_ask" as PermissionMode,
    timezone: "Asia/Shanghai",
    stateful: false,
    enabled: true,
  };
}

function getScheduleForm(schedule: ScheduleRecord) {
  const data = schedule.data;
  const [minute = "0", hour = "0", day = "*", month = "*", weekday = "*"] =
    data.cron_expression.split(" ");
  const date = new Date(data.started_at);
  if (month !== "*" && Number.isFinite(Number(month)))
    date.setMonth(Number(month) - 1);
  if (day !== "*" && Number.isFinite(Number(day))) date.setDate(Number(day));
  if (day === "*" && weekday !== "*" && Number.isFinite(Number(weekday)))
    date.setDate(date.getDate() + ((Number(weekday) - date.getDay() + 7) % 7));
  return {
    ...getDefaultForm(),
    name: data.name,
    description: data.description,
    freq: (month !== "*" && day !== "*"
      ? "once"
      : day !== "*"
        ? "monthly"
        : weekday !== "*"
          ? "weekly"
          : "daily") as FreqType,
    date,
    time: `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`,
    endDate: data.ended_at ? new Date(data.ended_at) : undefined,
    agentId: schedule.agent_id,
    projectId: data.project_id ?? "",
    chatModelConfig: data.chat_model_config,
    timezone: data.timezone,
    permissionMode: data.permission_mode,
    stateful: data.stateful,
    enabled: data.enabled,
  };
}

function buildCronExpr(
  freq: FreqType,
  time: string,
  date: Date | undefined,
): string {
  const [h, m] = time.split(":").map(Number);
  switch (freq) {
    case "daily":
      return `${m} ${h} * * *`;
    case "weekly": {
      const weekday = date ? date.getDay() : 1;
      return `${m} ${h} * * ${weekday}`;
    }
    case "monthly": {
      const monthDay = date ? date.getDate() : 1;
      return `${m} ${h} ${monthDay} * *`;
    }
    default:
      return "";
  }
}

function DatePickerButton({
  date,
  onSelect,
  placeholder,
  disabled,
}: {
  date: Date | undefined;
  onSelect: (d: Date | undefined) => void;
  placeholder: string;
  disabled?: boolean;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          disabled={disabled}
          className="w-32 justify-between font-normal"
        >
          {date ? format(date, "PPP") : placeholder}
          <ChevronDownIcon className="size-3.5 text-muted-foreground" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={date}
          onSelect={onSelect}
          captionLayout="dropdown"
        />
      </PopoverContent>
    </Popover>
  );
}

export function CreateScheduleDialog({
  open,
  onOpenChange,
  onCreated,
  schedule = null,
  onUpdated,
}: Props) {
  const { t } = useTranslation();
  const { create, update } = useSchedules();
  const { agents } = useAgents();
  const { data: projectsData } = useProjects();
  const [form, setForm] = React.useState(getDefaultForm);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const importInput = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (open) {
      setForm(schedule ? getScheduleForm(schedule) : getDefaultForm());
      setError("");
    }
  }, [open, schedule]);

  React.useEffect(() => {
    if (!schedule && agents.length > 0 && !form.agentId) {
      setForm((prev) => ({ ...prev, agentId: agents[0].id }));
    }
  }, [agents, form.agentId, schedule]);

  const selectableProjects = (projectsData?.projects ?? []).filter(
    (project) => project.agent_id === form.agentId,
  );

  const set = <K extends keyof ReturnType<typeof getDefaultForm>>(
    key: K,
    value: ReturnType<typeof getDefaultForm>[K],
  ) => setForm((prev) => ({ ...prev, [key]: value }));
  const importJson = async (file?: File) => {
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const s =
        parsed?.format === "agentscope-schedule/v1" ? parsed.schedule : null;
      if (!s?.name || !s.cron_expression || !s.agent_id || !s.chat_model_config)
        throw new Error("不是有效的 AgentScope 日程导出文件。");
      const [minute, hour, day, month, weekday] = String(
        s.cron_expression,
      ).split(" ");
      if (![minute, hour, day, month, weekday].every(Boolean))
        throw new Error("导入文件的 Cron 表达式无效。");
      const date = s.started_at ? new Date(s.started_at) : new Date();
      if (month !== "*" && Number.isFinite(Number(month)))
        date.setMonth(Number(month) - 1);
      if (day !== "*" && Number.isFinite(Number(day)))
        date.setDate(Number(day));
      if (day === "*" && weekday !== "*" && Number.isFinite(Number(weekday)))
        date.setDate(
          date.getDate() + ((Number(weekday) - date.getDay() + 7) % 7),
        );
      const freq: FreqType =
        month !== "*" && day !== "*"
          ? "once"
          : day !== "*"
            ? "monthly"
            : weekday !== "*"
              ? "weekly"
              : "daily";
      setForm({
        ...getDefaultForm(),
        name: s.name,
        description: s.description ?? "",
        freq,
        date,
        time: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`,
        endDate: s.ended_at ? new Date(s.ended_at) : undefined,
        agentId: s.agent_id,
        projectId: s.project_id ?? "",
        chatModelConfig: s.chat_model_config,
        timezone: s.timezone ?? "Asia/Shanghai",
        permissionMode: s.permission_mode ?? "dont_ask",
        stateful: !!s.stateful,
        enabled: s.enabled ?? true,
      });
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "导入失败");
    } finally {
      if (importInput.current) importInput.current.value = "";
    }
  };

  const isValid =
    form.name.trim() &&
    !!form.date &&
    !!form.time &&
    !!form.agentId &&
    !!form.chatModelConfig;

  const handleSubmit = async () => {
    setError("");
    if (!isValid) return;
    setLoading(true);
    try {
      let cronExpression: string;

      const d = new Date(form.date!);
      const [h, m] = form.time.split(":").map(Number);
      d.setHours(h, m, 0, 0);

      if (form.freq === "once") {
        cronExpression = `${m} ${h} ${d.getDate()} ${d.getMonth() + 1} *`;
      } else {
        cronExpression = buildCronExpr(form.freq, form.time, form.date);
      }

      const body = {
        name: form.name.trim(),
        description: form.description.trim(),
        cron_expression: cronExpression,
        timezone: form.timezone,
        agent_id: form.agentId,
        chat_model_config: form.chatModelConfig!,
        enabled: form.enabled,
        // Deliberately send a timezone-local, end-of-day value. The server's
        // CronTrigger interprets this in `timezone`; converting the browser
        // Date to UTC here would otherwise shift a date chosen in another zone.
        ended_at: form.endDate
          ? `${format(form.endDate, "yyyy-MM-dd")}T23:59:59`
          : null,
        stateful: form.stateful,
        permission_mode: form.permissionMode,
        project_id: form.projectId || null,
      };
      if (schedule) {
        await (onUpdated ?? update)(schedule.id, body);
      } else {
        await create({
          ...body,
          agent_id: form.agentId,
          chat_model_config: form.chatModelConfig!,
        });
        onCreated?.();
      }
      onOpenChange(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!w-[500px] !max-w-[500px]">
        <DialogHeader>
          <DialogTitle>
            {schedule ? "编辑日程" : t("schedule.createSchedule.title")}
          </DialogTitle>
          <DialogDescription>
            {schedule
              ? "修改后会立即重新计算下一次执行时间。智能体与模型保持创建时的配置。"
              : t("schedule.createSchedule.description")}
          </DialogDescription>
        </DialogHeader>

        {!schedule && (
          <div className="flex justify-end border-b pb-3">
            <input
              ref={importInput}
              type="file"
              accept="application/json,.json"
              hidden
              onChange={(e) => void importJson(e.target.files?.[0])}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => importInput.current?.click()}
            >
              <Upload className="size-4" />
              导入 JSON
            </Button>
          </div>
        )}

        <div className="no-scrollbar -mx-4 max-h-[75vh] overflow-y-auto px-4">
          <FieldGroup className="[&>[data-orientation=horizontal]>:last-child]:w-48">
            <Field>
              <FieldLabel>{t("common.name")}</FieldLabel>
              <Input
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder={t("schedule.createSchedule.namePlaceholder")}
              />
            </Field>
            <Field>
              <FieldLabel>
                {t("schedule.createSchedule.descriptionLabel")}
              </FieldLabel>
              <Textarea
                value={form.description}
                onChange={(e) => set("description", e.target.value)}
                placeholder={t(
                  "schedule.createSchedule.descriptionPlaceholder",
                )}
                className="min-h-[150px]"
              />
            </Field>

            <div className="flex gap-3">
              <Field className="flex-1">
                <FieldLabel>{t("common.date")}</FieldLabel>
                <DatePickerButton
                  date={form.date}
                  onSelect={(d) => d && set("date", d)}
                  placeholder={t("schedule.pickDate")}
                />
              </Field>
              <Field className="w-48">
                <FieldLabel>{t("common.time")}</FieldLabel>
                <Input
                  type="time"
                  value={form.time}
                  onChange={(e) => set("time", e.target.value)}
                  className="appearance-none [&::-webkit-calendar-picker-indicator]:hidden [&::-webkit-calendar-picker-indicator]:appearance-none"
                />
              </Field>
            </div>

            <Field orientation={"horizontal"}>
              <FieldLabel>{t("schedule.timezone")}</FieldLabel>
              <TimezoneSelect
                size="default"
                value={form.timezone}
                onChange={(v) => set("timezone", v)}
              />
            </Field>

            <Field orientation={"horizontal"}>
              <FieldLabel>{t("schedule.frequency")}</FieldLabel>
              <Select
                value={form.freq}
                onValueChange={(v) => set("freq", v as FreqType)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="once">{t("schedule.freqOnce")}</SelectItem>
                  <SelectItem value="daily">
                    {t("schedule.freqDaily")}
                  </SelectItem>
                  <SelectItem value="weekly">
                    {t("schedule.freqWeekly")}
                  </SelectItem>
                  <SelectItem value="monthly">
                    {t("schedule.freqMonthly")}
                  </SelectItem>
                </SelectContent>
              </Select>
            </Field>

            <Field orientation={"horizontal"}>
              <FieldLabel
                className={form.freq === "once" ? "text-muted-foreground" : ""}
              >
                {t("schedule.endAt")}
              </FieldLabel>
              <DatePickerButton
                date={form.freq === "once" ? undefined : form.endDate}
                onSelect={(d) => set("endDate", d)}
                placeholder={t("schedule.pickDate")}
                disabled={form.freq === "once"}
              />
            </Field>

            <Field orientation={"horizontal"}>
              <FieldLabel>{t("common.agent")}</FieldLabel>
              <AgentSelect
                size="default"
                agents={agents}
                value={form.agentId || null}
                onChange={(id) =>
                  setForm((previous) => ({
                    ...previous,
                    agentId: id,
                    projectId: "",
                  }))
                }
                disabled={!!schedule}
                placeholder={t("common.selectAgent")}
              />
            </Field>

            <Field orientation={"horizontal"}>
              <div className="flex min-w-0 flex-1 flex-col gap-1">
                <FieldLabel>项目</FieldLabel>
                <span className="text-xs text-muted-foreground">
                  后续新会话使用项目文件；历史会话保持原工作区。
                </span>
              </div>
              <Select
                value={form.projectId || "__none__"}
                onValueChange={(value) =>
                  set("projectId", value === "__none__" ? "" : value)
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">不使用项目</SelectItem>
                  {selectableProjects.map((project) => (
                    <SelectItem key={project.id} value={project.id}>
                      {project.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            <Field orientation={"horizontal"}>
              <FieldLabel>{t("common.model")}</FieldLabel>
              <LlmSelect
                size="default"
                value={form.chatModelConfig}
                onChange={(v) => set("chatModelConfig", v)}
              />
            </Field>

            <Field orientation={"horizontal"}>
              <FieldLabel>{t("schedule.permissionMode")}</FieldLabel>
              <PermissionModeSelect
                size="default"
                value={form.permissionMode}
                onChange={(v) => set("permissionMode", v)}
              />
            </Field>

            <Field>
              <div className="flex flex-row items-center justify-between">
                <div className="flex flex-col gap-y-0.5">
                  <FieldLabel>{t("schedule.stateful")}</FieldLabel>
                  <span className="text-xs text-muted-foreground">
                    {t("schedule.statefulDesc")}
                  </span>
                </div>
                <Switch
                  checked={form.stateful}
                  onCheckedChange={(v) => set("stateful", v)}
                />
              </div>
            </Field>

            <Field>
              <div className="flex flex-row items-center justify-between">
                <div className="flex flex-col gap-y-0.5">
                  <FieldLabel>启用日程</FieldLabel>
                  <span className="text-xs text-muted-foreground">
                    关闭后保留配置，但不会自动执行。
                  </span>
                </div>
                <Switch
                  checked={form.enabled}
                  onCheckedChange={(v) => set("enabled", v)}
                />
              </div>
            </Field>

            {error && <p className="text-sm text-destructive">{error}</p>}
          </FieldGroup>
        </div>

        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            <CircleAlert className="size-3.5" />
            {t("common.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={loading || !isValid}>
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <PlusCircle className="size-3.5" />
            )}
            {loading
              ? schedule
                ? "保存中…"
                : t("common.creating")
              : schedule
                ? "保存修改"
                : t("common.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
