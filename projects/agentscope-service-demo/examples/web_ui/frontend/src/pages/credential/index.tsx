import { useQueryClient } from "@tanstack/react-query";
import { Eye, EyeOff, Plus, Trash2, Pen, RefreshCw } from "lucide-react";
import { useState, useEffect, useCallback } from "react";

import { credentialApi, embeddingModelApi, modelApi, ttsModelApi } from "@/api";
import { client } from "@/api/client";
import { portalWrite } from "@/api/portal";
import type {
  CredentialView,
  CredentialSchema,
  EmbeddingModelCard,
  ModelCard,
  TTSModelCard,
} from "@/api";
import { CreateCredentialDialog } from "@/components/dialog/CreateCredentialDialog";
import { DeleteDialog } from "@/components/dialog/DeleteDialog";
import { EditCredentialDialog } from "@/components/dialog/EditCredentialDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { Separator } from "@/components/ui/separator";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCredentials } from "@/hooks/useCredentials";
import { useTranslation } from "@/i18n/useI18n";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/utils/common.ts";
import {
  explicitProviderModelCategory,
  PROVIDER_MODEL_CATEGORY_LABEL,
  type ProviderModelCategory,
} from "@/utils/modelCategory";

/** Which model list the detail panel is showing. */
type ModelTab = "llm" | "tts" | "embedding";

/** A row in the model table — one of the three card shapes. */
type ModelRow = ModelCard | TTSModelCard | EmbeddingModelCard;
type ModelConfiguration = {
  context_size?: number;
  output_size?: number;
  dimensions?: number;
  vision?: boolean;
};

// ─── Masked value ─────────────────────────────────────────────────────────────

function MaskedValue({ value }: { value: string }) {
  const [visible, setVisible] = useState(false);
  const masked =
    value.length > 8
      ? value.slice(0, 4) + "••••••••" + value.slice(-4)
      : "••••••••";
  return (
    <span className="flex items-center gap-x-1.5 font-mono text-sm">
      {visible ? value : masked}
      <Button
        size={"icon-sm"}
        className="text-text-tertiary hover:text-foreground"
        variant={"ghost"}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? <EyeOff /> : <Eye />}
      </Button>
    </span>
  );
}

// ─── Model table ──────────────────────────────────────────────────────────────

/** MIME main-types that stand on their own in the ACCEPTS / OUTPUTS cells. */
const MODALITIES = new Set(["text", "image", "video", "audio"]);

/** Marks a model as reasoning-capable; not a real input modality. */
const THINKING_TYPE = "application/x-thinking";

/** Dense-vector output of an embedding model. */
const EMBEDDING_TYPE = "application/x-embedding";

/**
 * Collapse a model's MIME list into short modality labels. Anything
 * outside the four media types (PDFs, office documents, …) folds into a
 * single `file` entry so the cell stays one line.
 *
 * @param types - MIME types straight off the model card.
 * @returns De-duplicated labels in encounter order.
 */
function modalities(types: string[]): string[] {
  const out = new Set<string>();
  for (const type of types) {
    if (type === THINKING_TYPE) continue;
    if (type === EMBEDDING_TYPE) {
      out.add("vector");
      continue;
    }
    const main = type.split("/")[0];
    out.add(MODALITIES.has(main) ? main : "file");
  }
  return [...out];
}

/** Inline pill sitting next to a model name (reasoning, realtime, status). */
function ModelTag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-surface-muted px-1.75 py-0.5 font-mono text-[9px] tracking-[0.06em] uppercase text-text-secondary">
      {children}
    </span>
  );
}

function HeadCell({ children }: { children: React.ReactNode }) {
  return (
    <TableHead className="h-auto bg-muted px-4 py-2.25 font-mono text-[9.5px] font-normal tracking-widest uppercase text-text-tertiary">
      {children}
    </TableHead>
  );
}

/** Numeric / modality cell — mono, one step darker than the head row. */
function DataCell({
  children,
  size,
}: {
  children: React.ReactNode;
  size: "11" | "11.5";
}) {
  return (
    <TableCell
      className={cn(
        "px-4 py-2.5 font-mono text-text-secondary",
        size === "11" ? "text-[11px]" : "text-[11.5px]",
      )}
    >
      {children}
    </TableCell>
  );
}

interface ModelTableProps {
  /** Rows to render; the shape must match `variant`. */
  models: ModelRow[];
  /** Drives which numeric columns sit between MODEL and ACCEPTS. */
  variant: ModelTab;
  enabledModels?: Set<string>;
  onEnabledChange?: (model: string, enabled: boolean) => void;
  modelTypes?: Partial<Record<string, ProviderModelCategory>>;
  onModelTypeChange?: (model: string, category: ProviderModelCategory) => void;
  configuredModels?: Set<string>;
  onConfigure?: (model: string) => void;
}

/**
 * The model list as a table: one row per model, sizes and modalities in
 * their own columns rather than repeated label/value pairs per card.
 *
 * @param models - Rows to render.
 * @param variant - Which column set applies.
 * @returns The bordered table plus its legend.
 */
function ModelTable({
  models,
  variant,
  enabledModels,
  onEnabledChange,
  modelTypes,
  onModelTypeChange,
  configuredModels,
  onConfigure,
}: ModelTableProps) {
  const { t } = useTranslation();
  const isChat = variant === "llm";
  const isEmbedding = variant === "embedding";

  return (
    <div>
      <div className="overflow-x-auto rounded-[16px] border border-border">
        <Table className="min-w-[500px]">
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <HeadCell>{t("credential.table.model")}</HeadCell>
              {onModelTypeChange && <HeadCell>模型类型</HeadCell>}
              {onConfigure && <HeadCell>配置</HeadCell>}
              {onEnabledChange && <HeadCell>启用</HeadCell>}
              {(isChat || isEmbedding) && (
                <HeadCell>{t("credential.table.context")}</HeadCell>
              )}
              {isChat && <HeadCell>{t("credential.table.maxOutput")}</HeadCell>}
              {isEmbedding && (
                <HeadCell>{t("credential.table.dimensions")}</HeadCell>
              )}
              <HeadCell>{t("credential.table.accepts")}</HeadCell>
              <HeadCell>{t("credential.table.outputs")}</HeadCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.map((model) => {
              const chat = isChat ? (model as ModelCard) : null;
              const embed = isEmbedding ? (model as EmbeddingModelCard) : null;
              const tts = variant === "tts" ? (model as TTSModelCard) : null;
              const context = chat?.context_size ?? embed?.context_size;
              return (
                <TableRow
                  key={model.name}
                  className="border-border hover:bg-row-hover"
                >
                  <TableCell className="px-4 py-2.5 text-[12.5px] text-foreground">
                    <span className="flex items-center gap-x-2">
                      <span
                        className="min-w-0 flex-1 truncate"
                        title={model.name}
                      >
                        {model.label || model.name}
                      </span>
                      {model.input_types.includes(THINKING_TYPE) && (
                        <ModelTag>{t("credential.reasoning")}</ModelTag>
                      )}
                      {tts?.realtime && (
                        <ModelTag>{t("credential.realtime")}</ModelTag>
                      )}
                      {model.status !== "active" && (
                        <ModelTag>{model.status}</ModelTag>
                      )}
                    </span>
                  </TableCell>
                  {onModelTypeChange && (
                    <TableCell className="px-4 py-2.5">
                      <select
                        aria-label={`${model.name} 的模型类型`}
                        value={modelTypes?.[model.name] ?? ""}
                        onChange={(event) => {
                          const category = explicitProviderModelCategory(
                            event.target.value,
                          );
                          if (category) onModelTypeChange(model.name, category);
                        }}
                        className="h-8 min-w-31 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-2 focus:ring-ring"
                      >
                        <option value="">选择类型</option>
                        {(
                          Object.keys(
                            PROVIDER_MODEL_CATEGORY_LABEL,
                          ) as ProviderModelCategory[]
                        ).map((category) => (
                          <option key={category} value={category}>
                            {PROVIDER_MODEL_CATEGORY_LABEL[category]}
                          </option>
                        ))}
                      </select>
                    </TableCell>
                  )}
                  {onConfigure && (
                    <TableCell className="px-4 py-2.5">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-8 px-2.5 text-xs"
                        disabled={!modelTypes?.[model.name]}
                        onClick={() => onConfigure(model.name)}
                      >
                        {configuredModels?.has(model.name) ? "已配置" : "配置"}
                      </Button>
                    </TableCell>
                  )}
                  {onEnabledChange && (
                    <TableCell className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        aria-label={`启用 ${model.name}`}
                        checked={enabledModels?.has(model.name) ?? true}
                        disabled={
                          !modelTypes?.[model.name] ||
                          !configuredModels?.has(model.name)
                        }
                        title={
                          !modelTypes?.[model.name]
                            ? "请先选择模型类型"
                            : !configuredModels?.has(model.name)
                              ? "请先完成模型配置"
                              : undefined
                        }
                        onChange={(event) =>
                          onEnabledChange(model.name, event.target.checked)
                        }
                        className="size-4 accent-emerald-600"
                      />
                    </TableCell>
                  )}
                  {(isChat || isEmbedding) && (
                    <DataCell size="11.5">
                      {context ? formatNumber(context) : "—"}
                    </DataCell>
                  )}
                  {isChat && (
                    <DataCell size="11.5">
                      {chat?.output_size ? formatNumber(chat.output_size) : "—"}
                    </DataCell>
                  )}
                  {isEmbedding && (
                    <DataCell size="11.5">{embed?.dimensions ?? "—"}</DataCell>
                  )}
                  <DataCell size="11">
                    {modalities(model.input_types).join(" · ") || "—"}
                  </DataCell>
                  <DataCell size="11">
                    {modalities(model.output_types).join(" · ") || "—"}
                  </DataCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      <p className="mt-2.5 text-[11px] text-muted-foreground">
        {t("credential.table.legend")}
      </p>
    </div>
  );
}

// ─── Detail panel ─────────────────────────────────────────────────────────────

interface DetailPanelProps {
  credential: CredentialView;
  schema: CredentialSchema | null;
  onEdit: () => void;
  onDelete: () => void;
}

function DetailPanel({
  credential,
  schema,
  onEdit,
  onDelete,
}: DetailPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [models, setModels] = useState<ModelCard[]>([]);
  const [ttsModels, setTtsModels] = useState<TTSModelCard[]>([]);
  const [embeddingModels, setEmbeddingModels] = useState<EmbeddingModelCard[]>(
    [],
  );
  const [modelsLoading, setModelsLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");
  const [enabledModels, setEnabledModels] = useState<Set<string>>(new Set());
  const [modelTypes, setModelTypes] = useState<
    Partial<Record<string, ProviderModelCategory>>
  >({});
  const [modelConfigs, setModelConfigs] = useState<
    Record<string, ModelConfiguration>
  >({});
  const [configuringModel, setConfiguringModel] = useState<string | null>(null);
  const [configDraft, setConfigDraft] = useState<ModelConfiguration>({});
  const [tab, setTab] = useState<ModelTab>("llm");
  const [category, setCategory] = useState<ProviderModelCategory | "all">(
    "all",
  );

  const type = credential.data.type as string | undefined;
  const isLiveProvider =
    type === "deepseek_credential" || type === "openai_credential";
  const shown =
    tab === "llm" ? models : tab === "tts" ? ttsModels : embeddingModels;
  const total = models.length + ttsModels.length + embeddingModels.length;
  const categoryCounts = models.reduce(
    (counts, model) => {
      const modelCategory = explicitProviderModelCategory(
        modelTypes[model.name] ?? model.category,
      );
      if (modelCategory) counts[modelCategory] += 1;
      return counts;
    },
    {
      llm: 0,
      embedding: 0,
      rerank: 0,
      stt: 0,
      tts: 0,
    } satisfies Record<ProviderModelCategory, number>,
  );
  const categorizedModels =
    isLiveProvider && category !== "all"
      ? models.filter(
          (model) =>
            explicitProviderModelCategory(
              modelTypes[model.name] ?? model.category,
            ) === category,
        )
      : models;
  const hasExplicitCategories = Object.values(categoryCounts).some(
    (count) => count > 0,
  );
  // A credential switch can land on a provider with no TTS models at
  // all, which would leave the tab pointing at an empty list.
  useEffect(() => {
    setTab("llm");
    setCategory("all");
  }, [credential.id]);

  useEffect(() => {
    if (!type) return;
    setModelsLoading(true);
    if (type === "deepseek_credential" || type === "openai_credential") {
      client
        .get<{
          models: ModelCard[];
          enabled_models?: string[];
          model_types?: Partial<Record<string, ProviderModelCategory>>;
          model_configs?: Record<string, ModelConfiguration>;
        }>(`/portal/models/${encodeURIComponent(credential.id)}`)
        .then((result) => {
          setModels(result.models);
          setEnabledModels(new Set(result.enabled_models ?? []));
          setModelTypes(result.model_types ?? {});
          setModelConfigs(result.model_configs ?? {});
          setTtsModels([]);
          setEmbeddingModels([]);
        })
        .catch(() => setModels([]))
        .finally(() => setModelsLoading(false));
      return;
    }
    Promise.all([
      modelApi
        .list(type)
        .then((res) => res.models)
        .catch(() => [] as ModelCard[]),
      ttsModelApi
        .list(type)
        .then((res) => res.models)
        .catch(() => [] as TTSModelCard[]),
      embeddingModelApi
        .list(type)
        .then((res) => res.models)
        .catch(() => [] as EmbeddingModelCard[]),
    ])
      .then(([chatModels, tts, embeddings]) => {
        setModels(chatModels);
        setEnabledModels(new Set());
        setModelTypes({});
        setModelConfigs({});
        setTtsModels(tts);
        setEmbeddingModels(embeddings);
      })
      .finally(() => setModelsLoading(false));
  }, [credential.id, type]);

  const refreshModels = async () => {
    setRefreshing(true);
    setRefreshError("");
    try {
      await portalWrite<{ models: string[] }>(
        `/portal/models/${encodeURIComponent(credential.id)}/refresh`,
        "POST",
      );
      // Re-read the normalized server response. This is the same path used
      // on page load, so provider IDs, labels and built-in metadata do not
      // visually change after a browser refresh.
      const result = await client.get<{
        models: ModelCard[];
        enabled_models?: string[];
        model_types?: Partial<Record<string, ProviderModelCategory>>;
        model_configs?: Record<string, ModelConfiguration>;
      }>(`/portal/models/${encodeURIComponent(credential.id)}`);
      setModels(result.models);
      setEnabledModels(new Set(result.enabled_models ?? []));
      setModelTypes(result.model_types ?? {});
      setModelConfigs(result.model_configs ?? {});
      setTtsModels([]);
      setEmbeddingModels([]);
      setTab("llm");
    } catch (error) {
      setRefreshError(error instanceof Error ? error.message : "刷新模型失败");
    } finally {
      setRefreshing(false);
    }
  };

  const toggleModel = async (name: string, enabled: boolean) => {
    if (enabled && !modelTypes[name]) {
      setRefreshError("请先选择模型类型，再启用模型");
      return;
    }
    const previous = enabledModels;
    const next = new Set(previous);
    enabled ? next.add(name) : next.delete(name);
    setEnabledModels(next);
    try {
      const result = await portalWrite<{ enabled_models: string[] }>(
        `/portal/models/${encodeURIComponent(credential.id)}/enabled`,
        "PUT",
        {
          enabled_models: [...next],
          model_types: modelTypes,
          model_configs: modelConfigs,
        },
      );
      setEnabledModels(new Set(result.enabled_models));
    } catch (error) {
      setEnabledModels(previous);
      setRefreshError(
        error instanceof Error ? error.message : "保存模型状态失败",
      );
    }
  };

  const setModelType = async (
    name: string,
    category: ProviderModelCategory,
  ) => {
    const previous = modelTypes;
    const next = { ...previous, [name]: category };
    const nextEnabled = new Set(enabledModels);
    nextEnabled.delete(name);
    const nextConfigs = { ...modelConfigs };
    delete nextConfigs[name];
    setModelTypes(next);
    setEnabledModels(nextEnabled);
    setModelConfigs(nextConfigs);
    setModels((current) =>
      current.map((model) =>
        model.name === name ? { ...model, category } : model,
      ),
    );
    try {
      const result = await portalWrite<{ enabled_models: string[] }>(
        `/portal/models/${encodeURIComponent(credential.id)}/enabled`,
        "PUT",
        {
          enabled_models: [...nextEnabled],
          model_types: next,
          model_configs: nextConfigs,
        },
      );
      setEnabledModels(new Set(result.enabled_models));
    } catch (error) {
      setModelTypes(previous);
      setEnabledModels(enabledModels);
      setModelConfigs(modelConfigs);
      setModels((current) =>
        current.map((model) =>
          model.name === name ? { ...model, category: previous[name] } : model,
        ),
      );
      setRefreshError(
        error instanceof Error ? error.message : "保存模型类型失败",
      );
    }
  };

  const openModelConfiguration = (name: string) => {
    setConfiguringModel(name);
    const existing = modelConfigs[name] ?? {};
    setConfigDraft({
      ...existing,
      vision: existing.vision ?? models.find((model) => model.name === name)?.input_types.some((mime) => mime.startsWith("image/")) ?? false,
    });
  };

  const saveModelConfiguration = async () => {
    if (!configuringModel) return;
    const category = modelTypes[configuringModel];
    if (!category) return;
    const positive = (value: number | undefined) =>
      typeof value === "number" && value > 0;
    if (
      (category === "llm" &&
        (!positive(configDraft.context_size) ||
          !positive(configDraft.output_size))) ||
      (category === "embedding" && !positive(configDraft.dimensions)) ||
      (category === "rerank" && !positive(configDraft.context_size))
    ) {
      setRefreshError("请填写该模型类型要求的全部配置项");
      return;
    }
    const previous = modelConfigs;
    const next = { ...previous, [configuringModel]: configDraft };
    setModelConfigs(next);
    try {
      const result = await portalWrite<{ enabled_models: string[] }>(
        `/portal/models/${encodeURIComponent(credential.id)}/enabled`,
        "PUT",
        {
          enabled_models: [...enabledModels],
          model_types: modelTypes,
          model_configs: next,
        },
      );
      setEnabledModels(new Set(result.enabled_models));
      setModels((current) => current.map((model) => {
        if (model.name !== configuringModel || category !== "llm") return model;
        const inputTypes = model.input_types.filter((mime) => !mime.startsWith("image/"));
        if (configDraft.vision) inputTypes.push("image/*");
        return { ...model, input_types: inputTypes };
      }));
      await queryClient.invalidateQueries({ queryKey: ["available-models"] });
      setConfiguringModel(null);
    } catch (error) {
      setModelConfigs(previous);
      setRefreshError(
        error instanceof Error ? error.message : "保存模型配置失败",
      );
    }
  };

  // Fields to display: use schema properties order, skip id/type/const fields
  const displayFields = schema
    ? Object.entries(schema.properties).filter(
        ([key, prop]) =>
          key !== "id" && key !== "type" && prop.const === undefined,
      )
    : Object.entries(credential.data)
        .filter(([key]) => key !== "id" && key !== "type")
        .map(
          ([key]) =>
            [key, { title: key, writeOnly: false }] as [
              string,
              { title: string; writeOnly: boolean },
            ],
        );

  const name = (credential.data.name as string | undefined) ?? credential.id;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="shrink-0 flex items-start justify-between gap-x-4 p-[18px_18px_16px]">
        <div className="flex flex-col gap-y-1">
          <span className="text-foreground text-lg font-medium tracking-[-0.015em]">
            {name}
          </span>
          <span className="font-mono text-text-data text-sm">{type}</span>
          {!credential.editable && (
            <Badge variant="secondary" title={t("common.readOnlyTooltip")}>
              {t("common.readOnly")}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-x-2 shrink-0">
          <Button
            size="icon-sm"
            variant="ghost"
            className="text-text-tertiary hover:text-foreground"
            onClick={() => void refreshModels()}
            disabled={!credential.editable || refreshing}
            tooltip={
              credential.editable ? "刷新可用模型" : t("common.readOnlyTooltip")
            }
          >
            <RefreshCw className={refreshing ? "animate-spin" : ""} />
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            className="text-text-tertiary hover:text-foreground"
            onClick={onEdit}
            disabled={!credential.editable}
            tooltip={
              credential.editable ? undefined : t("common.readOnlyTooltip")
            }
          >
            <Pen />
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            className="text-text-tertiary hover:bg-destructive/8 hover:text-destructive"
            onClick={onDelete}
            disabled={!credential.editable}
            tooltip={
              credential.editable ? undefined : t("common.readOnlyTooltip")
            }
          >
            <Trash2 />
          </Button>
        </div>
      </div>

      <Separator className="shrink-0" />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {/* Fields */}
        <div className="flex flex-col gap-y-3 p-[20px_18px_0]">
          {displayFields.map(([key, prop]) => {
            const schemaProp = prop as {
              title?: string;
              writeOnly?: boolean;
              format?: string;
            };
            const label = schemaProp.title ?? key.replace(/_/g, " ");
            const isSecret =
              schemaProp.writeOnly || schemaProp.format === "password";
            const val = credential.data[key];
            if (val === undefined || val === null) return null;
            const strVal = String(val);
            return (
              <div
                key={key}
                className="grid grid-cols-[104px_1fr] gap-x-4.5 gap-y-3 items-baseline font-mono"
              >
                <span className="text-[10px] text-text-tertiary tracking-[0.12em] uppercase">
                  {label}
                </span>
                {isSecret ? (
                  <MaskedValue value={strVal} />
                ) : (
                  <span className="text-sm text-foreground break-all">
                    {strVal}
                  </span>
                )}
              </div>
            );
          })}
          <div className="grid grid-cols-[104px_1fr] items-baseline gap-x-4.5 font-mono">
            <span className="text-[10px] tracking-[0.12em] text-text-tertiary uppercase">
              ID
            </span>
            <span
              className="break-all text-xs text-text-secondary"
              title={credential.id}
            >
              {credential.id}
            </span>
          </div>
        </div>

        {/* Available Models */}
        <Tabs
          value={tab}
          onValueChange={(v) => setTab(v as ModelTab)}
          className="gap-0 px-[18px] pb-6"
        >
          <div className="mt-[30px] mb-3 flex items-center justify-between">
            <span className="flex items-center gap-x-2 text-[13.5px] font-medium text-foreground">
              {t("credential.availableModels")}
              <span className="font-mono text-[11px] text-text-data">
                {total}
              </span>
            </span>
            {/* Only worth a switch when there is a second list to switch to. */}
            {(ttsModels.length > 0 || embeddingModels.length > 0) && (
              <TabsList className="bg-surface-muted">
                {/* Only the shadow is overridden here; the stock one
							    is shadow-sm. */}
                <TabsTrigger
                  value="llm"
                  className="px-2.5 text-[11.5px] text-muted-foreground group-data-[variant=default]/tabs-list:data-active:shadow-tab!"
                >
                  {t("common.llm")}
                  <span className="font-mono text-[10px] text-text-data">
                    {models.length}
                  </span>
                </TabsTrigger>
                {ttsModels.length > 0 && (
                  <TabsTrigger
                    value="tts"
                    className="px-2.5 text-[11.5px] text-muted-foreground group-data-[variant=default]/tabs-list:data-active:shadow-tab!"
                  >
                    {t("common.tts")}
                    <span className="font-mono text-[10px] text-text-data">
                      {ttsModels.length}
                    </span>
                  </TabsTrigger>
                )}
                {embeddingModels.length > 0 && (
                  <TabsTrigger
                    value="embedding"
                    className="px-2.5 text-[11.5px] text-muted-foreground group-data-[variant=default]/tabs-list:data-active:shadow-tab!"
                  >
                    {t("common.embedding")}
                    <span className="font-mono text-[10px] text-text-data">
                      {embeddingModels.length}
                    </span>
                  </TabsTrigger>
                )}
              </TabsList>
            )}
          </div>

          {isLiveProvider && hasExplicitCategories && !modelsLoading && (
            <div className="mb-3 flex flex-wrap items-center gap-1.5">
              <Button
                type="button"
                size="sm"
                variant={category === "all" ? "default" : "outline"}
                className="h-7 rounded-full px-3 text-xs"
                onClick={() => setCategory("all")}
              >
                全部{" "}
                <span className="ml-1 font-mono text-[10px]">
                  {models.length}
                </span>
              </Button>
              {(
                Object.keys(
                  PROVIDER_MODEL_CATEGORY_LABEL,
                ) as ProviderModelCategory[]
              )
                .filter((key) => categoryCounts[key] > 0)
                .map((key) => (
                  <Button
                    key={key}
                    type="button"
                    size="sm"
                    variant={category === key ? "default" : "outline"}
                    className="h-7 rounded-full px-3 text-xs"
                    onClick={() => setCategory(key)}
                  >
                    {PROVIDER_MODEL_CATEGORY_LABEL[key]}
                    <span className="ml-1 font-mono text-[10px]">
                      {categoryCounts[key]}
                    </span>
                  </Button>
                ))}
              <span className="ml-1 text-[11px] text-muted-foreground">
                按模型能力分类
              </span>
            </div>
          )}

          {modelsLoading ? (
            <Skeleton className="h-40 rounded-[16px]" />
          ) : refreshError ? (
            <p role="alert" className="py-4 text-sm text-destructive">
              {refreshError}
            </p>
          ) : shown.length === 0 ? (
            <Empty className="border-none py-6">
              <EmptyHeader>
                <EmptyTitle>{t("credential.noModels")}</EmptyTitle>
                <EmptyDescription>
                  {t("credential.noModelsDescription")}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <>
              <TabsContent value="llm">
                <ModelTable
                  models={categorizedModels}
                  variant="llm"
                  enabledModels={enabledModels}
                  onEnabledChange={toggleModel}
                  modelTypes={modelTypes}
                  onModelTypeChange={setModelType}
                  configuredModels={new Set(Object.keys(modelConfigs))}
                  onConfigure={openModelConfiguration}
                />
              </TabsContent>
              <TabsContent value="tts">
                <ModelTable models={ttsModels} variant="tts" />
              </TabsContent>
              <TabsContent value="embedding">
                <ModelTable models={embeddingModels} variant="embedding" />
              </TabsContent>
            </>
          )}
        </Tabs>
        <Dialog
          open={configuringModel !== null}
          onOpenChange={(open) => !open && setConfiguringModel(null)}
        >
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>配置模型</DialogTitle>
              <DialogDescription className="break-all">
                {configuringModel} ·{" "}
                {configuringModel && modelTypes[configuringModel]
                  ? PROVIDER_MODEL_CATEGORY_LABEL[modelTypes[configuringModel]!]
                  : ""}
              </DialogDescription>
            </DialogHeader>
            {configuringModel && modelTypes[configuringModel] === "llm" && (
              <div className="grid gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={configDraft.vision ?? false}
                    onChange={(event) => setConfigDraft((draft) => ({ ...draft, vision: event.target.checked }))}
                  />
                  支持图片输入（视觉）
                </label>
                <p className="text-xs text-muted-foreground">
                  模型及推理服务支持图片时开启，聊天中即可上传图片；此选项不会赋予纯文本模型视觉能力。
                </p>
                <label className="grid gap-1.5 text-sm">
                  上下文窗口（Token）
                  <Input
                    type="number"
                    min="1"
                    value={configDraft.context_size ?? ""}
                    onChange={(event) =>
                      setConfigDraft((draft) => ({
                        ...draft,
                        context_size: Number(event.target.value) || undefined,
                      }))
                    }
                  />
                </label>
                <label className="grid gap-1.5 text-sm">
                  最大输出（Token）
                  <Input
                    type="number"
                    min="1"
                    value={configDraft.output_size ?? ""}
                    onChange={(event) =>
                      setConfigDraft((draft) => ({
                        ...draft,
                        output_size: Number(event.target.value) || undefined,
                      }))
                    }
                  />
                </label>
              </div>
            )}
            {configuringModel &&
              modelTypes[configuringModel] === "embedding" && (
                <div className="grid gap-1.5 text-sm">
                  <label className="grid gap-1.5">
                    向量维度
                    <Input
                      type="number"
                      min="1"
                      value={configDraft.dimensions ?? ""}
                      onChange={(event) =>
                        setConfigDraft((draft) => ({
                          ...draft,
                          dimensions: Number(event.target.value) || undefined,
                        }))
                      }
                    />
                  </label>
                  <p className="text-xs text-muted-foreground">
                    创建知识库后维度会固定，须与供应商模型实际输出一致。
                  </p>
                </div>
              )}
            {configuringModel && modelTypes[configuringModel] === "rerank" && (
              <label className="grid gap-1.5 text-sm">
                上下文窗口（Token）
                <Input
                  type="number"
                  min="1"
                  value={configDraft.context_size ?? ""}
                  onChange={(event) =>
                    setConfigDraft((draft) => ({
                      ...draft,
                      context_size: Number(event.target.value) || undefined,
                    }))
                  }
                />
              </label>
            )}
            {configuringModel &&
              (modelTypes[configuringModel] === "stt" ||
                modelTypes[configuringModel] === "tts") && (
                <p className="text-sm text-muted-foreground">
                  该类型暂不需要额外参数。保存后即可启用。
                </p>
              )}
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setConfiguringModel(null)}
              >
                取消
              </Button>
              <Button onClick={() => void saveModelConfiguration()}>
                保存配置
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export const CredentialPage = () => {
  const { t } = useTranslation();
  const { credentials, loading, remove, refetch } = useCredentials();
  const [schemas, setSchemas] = useState<CredentialSchema[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createDefaultType, setCreateDefaultType] = useState<
    string | undefined
  >();
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [search, setSearch] = useState("");

  useEffect(() => {
    credentialApi.schemas().then((res) => setSchemas(res.schemas));
  }, []);

  // Auto-select first credential
  useEffect(() => {
    if (!selectedId && credentials.length > 0) {
      setSelectedId(credentials[0].id);
    }
  }, [credentials, selectedId]);

  const selectedCredential =
    credentials.find((c) => c.id === selectedId) ?? null;
  const selectedSchema = selectedCredential
    ? (schemas.find(
        (s) =>
          (s.properties.type?.const as string) ===
          (selectedCredential.data.type as string),
      ) ?? null)
    : null;

  // Group credentials by type, then list all schema types (even empty ones)
  const normalizedSearch = search.trim().toLowerCase();
  const searchedCredentials = normalizedSearch
    ? credentials.filter((credential) => {
        const name = (credential.data.name as string | undefined) ?? "";
        return (
          name.toLowerCase().includes(normalizedSearch) ||
          credential.id.toLowerCase().includes(normalizedSearch)
        );
      })
    : credentials;

  const groupedByType: Array<{
    type: string;
    title: string;
    records: CredentialView[];
  }> = schemas.map((s) => {
    const type = s.properties.type?.const as string;
    return {
      type,
      title: s.title,
      records: searchedCredentials.filter((c) => c.data.type === type),
    };
  });

  // Split providers so the user's actual configuration leads, and the
  // (mostly empty) "add a provider" entries don't drown it out.
  const configuredGroups = groupedByType.filter((g) => g.records.length > 0);
  const totalConfigured = configuredGroups.reduce(
    (n, g) => n + g.records.length,
    0,
  );

  const handleOpenCreate = useCallback((type?: string) => {
    setCreateDefaultType(type);
    setCreateOpen(true);
  }, []);

  const handleDelete = useCallback(async () => {
    if (!selectedCredential) return;
    await remove(selectedCredential.id);
    setSelectedId(null);
  }, [selectedCredential, remove]);

  return (
    <div className="flex h-full w-full p-2 gap-2">
      {/* Left sidebar */}
      <Sidebar collapsible="none" className="rounded-[22px]">
        <SidebarHeader className={"flex flex-col p-[20px_18px_14px] gap-y-1"}>
          <div className="text-xl font-medium tracking-[-0.02em] text-foreground">
            {t("common.credential")}
          </div>
          <div className="text-text-tertiary text-xs">
            {t("credential.subtitle")}
          </div>
        </SidebarHeader>
        {/*<Separator />*/}
        <SidebarContent>
          <div className="px-4 pt-2">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索名称或凭证 ID"
              aria-label="搜索名称或凭证 ID"
              className="h-8 text-xs"
            />
          </div>
          {loading ? (
            <div className="flex flex-col gap-y-2 p-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-8 rounded" />
              ))}
            </div>
          ) : groupedByType.length === 0 ? (
            <Empty className="border-none py-8">
              <EmptyHeader>
                <EmptyTitle>{t("credential.noProviders")}</EmptyTitle>
              </EmptyHeader>
            </Empty>
          ) : (
            <>
              {/* Configured credentials lead — this is what the user actually set up. */}
              {configuredGroups.length > 0 && (
                <SidebarGroup className="mt-6 px-2 py-0">
                  <SidebarGroupLabel className="justify-between">
                    {t("credential.configured")}
                    <span className="text-[10px] text-text-data font-mono">
                      {totalConfigured}
                    </span>
                  </SidebarGroupLabel>
                  <SidebarGroupContent>
                    {configuredGroups.map(({ type, title, records }) => (
                      <SidebarGroup key={type} className="mt-3 px-0 py-0">
                        <SidebarGroupLabel>{title}</SidebarGroupLabel>
                        <SidebarGroupContent>
                          <SidebarMenu>
                            {records.map((rec) => {
                              const name =
                                (rec.data.name as string | undefined) ?? rec.id;
                              return (
                                <SidebarMenuItem key={rec.id}>
                                  <SidebarMenuButton
                                    isActive={selectedId === rec.id}
                                    onClick={() => setSelectedId(rec.id)}
                                  >
                                    <span className="min-w-0 flex-1 truncate">
                                      {name}
                                    </span>
                                    {!rec.editable && (
                                      <Badge
                                        variant="secondary"
                                        className="text-[10px] px-1 py-0"
                                        title={t("common.readOnlyTooltip")}
                                      >
                                        {t("common.readOnly")}
                                      </Badge>
                                    )}
                                  </SidebarMenuButton>
                                </SidebarMenuItem>
                              );
                            })}
                          </SidebarMenu>
                        </SidebarGroupContent>
                      </SidebarGroup>
                    ))}
                  </SidebarGroupContent>
                </SidebarGroup>
              )}

              {/* Add credential — every provider is an entry point (including
							    configured ones, to add more under the same provider). */}
              <SidebarGroup className="mt-5 px-2 py-0">
                <SidebarGroupLabel>
                  {t("credential.addProvider")}
                </SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {groupedByType.map(({ type, title }) => (
                      <SidebarMenuItem key={type}>
                        <SidebarMenuButton
                          onClick={() => handleOpenCreate(type)}
                        >
                          <Plus />
                          <span className="min-w-0 flex-1 truncate">
                            {title}
                          </span>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    ))}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            </>
          )}
        </SidebarContent>
      </Sidebar>

      {/* Right detail */}
      <main className="flex-1 min-h-0 overflow-hidden rounded-[22px] bg-card shadow-panel">
        {selectedCredential ? (
          <DetailPanel
            credential={selectedCredential}
            schema={selectedSchema}
            onEdit={() => setEditOpen(true)}
            onDelete={() => setDeleteOpen(true)}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <Empty className="border-none">
              <EmptyHeader>
                <EmptyTitle>{t("credential.selectHint")}</EmptyTitle>
                <EmptyDescription>
                  {t("credential.selectHintDescription")}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          </div>
        )}
      </main>

      {/* Dialogs */}
      <CreateCredentialDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        defaultType={createDefaultType}
        onCreated={() => refetch()}
      />
      {selectedCredential && (
        <>
          <EditCredentialDialog
            open={editOpen}
            onOpenChange={setEditOpen}
            credential={selectedCredential}
            onUpdated={() => refetch()}
          />
          <DeleteDialog
            open={deleteOpen}
            onOpenChange={setDeleteOpen}
            title={t("common.deleteTitle", {
              entity: t("credential.deleteEntity"),
              name:
                (selectedCredential.data.name as string | undefined) ??
                selectedCredential.id,
            })}
            description={t("common.deleteDescription")}
            onConfirm={handleDelete}
          />
        </>
      )}
    </div>
  );
};
