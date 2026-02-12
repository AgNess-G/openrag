/**
 * OpenRAG Knowledge Settings MCP App - Configure embedding and ingest settings.
 */
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { Minus, Plus } from "lucide-react";
import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import "../globals.css";

const EMBEDDING_PROVIDERS = ["openai", "ollama", "watsonx"] as const;

/** Get tool result text from either content[] or structuredContent.result[] (host-dependent). */
function getToolResultText(
  result: {
    content?: Array<{ type: string; text?: string }>;
    structuredContent?: { result?: Array<{ type: string; text?: string }> };
  }
): string | undefined {
  const fromContent = result.content?.find((c) => c.type === "text")?.text;
  if (fromContent) return fromContent;
  return result.structuredContent?.result?.find((c) => c.type === "text")?.text;
}

interface ModelOption {
  value: string;
  label?: string;
  default?: boolean;
}

interface KnowledgeSettings {
  embedding_provider: string;
  embedding_model: string;
  chunk_size: number;
  chunk_overlap: number;
  table_structure: boolean;
  ocr: boolean;
  picture_descriptions: boolean;
}

function KnowledgeSettingsApp() {
  const [knowledge, setKnowledge] = useState<KnowledgeSettings>({
    embedding_provider: "",
    embedding_model: "",
    chunk_size: 1024,
    chunk_overlap: 50,
    table_structure: true,
    ocr: false,
    picture_descriptions: false,
  });
  const [savingKnowledge, setSavingKnowledge] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [embeddingModels, setEmbeddingModels] = useState<ModelOption[]>([]);
  const [loadingEmbeddingModels, setLoadingEmbeddingModels] = useState(false);

  const { app, error: appError } = useApp({
    appInfo: { name: "OpenRAG Knowledge Settings", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (a) => {
      a.ontoolresult = async (result) => {
        const textContent = getToolResultText(result);
        if (!textContent) return;
        try {
          const data = JSON.parse(textContent);
          if (data.embedding_provider !== undefined || data.embedding_model !== undefined || data.chunk_size !== undefined) {
            setKnowledge((prev) => ({ ...prev, ...data }));
          }
          setError(null);
        } catch {
          setError("Failed to parse knowledge settings");
        }
      };
    },
  });

  const refresh = useCallback(async () => {
    if (!app) return;
    setRefreshing(true);
    setError(null);
    try {
      const result = await app.callServerTool({
        name: "openrag_get_knowledge_settings",
        arguments: {},
      });
      const textContent = getToolResultText(result);
      if (textContent) {
        const data = JSON.parse(textContent);
        setKnowledge((prev) => ({ ...prev, ...data }));
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRefreshing(false);
    }
  }, [app]);

  const updateKnowledgeSettings = useCallback(
    async (args: Record<string, unknown>) => {
      if (!app) return { error: null };
      try {
        const result = await app.callServerTool({
          name: "openrag_update_knowledge_settings",
          arguments: args,
        });
        const textContent = getToolResultText(result);
        if (textContent) {
          const data = JSON.parse(textContent);
          return { error: data.error ?? null };
        }
        return { error: null };
      } catch (e) {
        return { error: String(e) };
      }
    },
    [app]
  );

  const saveKnowledgeSettings = useCallback(async () => {
    setSavingKnowledge(true);
    setError(null);
    try {
      const { error: err } = await updateKnowledgeSettings({
        embedding_provider: knowledge.embedding_provider || undefined,
        embedding_model: knowledge.embedding_model || undefined,
        chunk_size: knowledge.chunk_size,
        chunk_overlap: knowledge.chunk_overlap,
        table_structure: knowledge.table_structure,
        ocr: knowledge.ocr,
        picture_descriptions: knowledge.picture_descriptions,
      });
      if (err) setError(err);
    } finally {
      setSavingKnowledge(false);
    }
  }, [knowledge, updateKnowledgeSettings]);

  const handleEmbeddingModelChange = useCallback(
    async (embeddingProvider: string, embeddingModel: string) => {
      setKnowledge((k) => ({
        ...k,
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel,
      }));
      if (!embeddingModel) return;
      const { error: err } = await updateKnowledgeSettings({
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel,
      });
      if (err) setError(err);
    },
    [updateKnowledgeSettings]
  );

  function getEmbeddingModelPlaceholder(): string {
    if (loadingEmbeddingModels) return "Loading models...";
    if (knowledge.embedding_provider)
      return "No embedding models detected. Configure a provider first.";
    return "Select provider first";
  }

  const loadEmbeddingModels = useCallback(
    async (provider: string) => {
      if (!app || !provider) {
        setEmbeddingModels([]);
        return;
      }
      setLoadingEmbeddingModels(true);
      try {
        const result = await app.callServerTool({
          name: "openrag_list_models",
          arguments: { provider },
        });
        const textContent = getToolResultText(result);
        if (textContent) {
          const parsed = JSON.parse(textContent);
          if (!parsed.error && parsed.embedding_models) {
            setEmbeddingModels(parsed.embedding_models);
          } else {
            setEmbeddingModels([]);
          }
        } else {
          setEmbeddingModels([]);
        }
      } catch {
        setEmbeddingModels([]);
      } finally {
        setLoadingEmbeddingModels(false);
      }
    },
    [app]
  );

  useEffect(() => {
    if (app) {
      refresh();
    }
  }, [app, refresh]);

  useEffect(() => {
    if (app && knowledge.embedding_provider) loadEmbeddingModels(knowledge.embedding_provider);
    else setEmbeddingModels([]);
  }, [app, knowledge.embedding_provider, loadEmbeddingModels]);

  if (appError) return <div className="text-destructive p-4">Error: {appError.message}</div>;
  if (!app) return <div className="p-4 text-muted-foreground">Connecting...</div>;

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card className="p-5 pt-0">
        <CardHeader className="space-y-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">Knowledge Ingest</CardTitle>
            <div className="flex gap-2">
              <Button variant="outline" size="sm">
                Restore flow
              </Button>
              <Button variant="outline" size="sm">
                Edit in Langflow
              </Button>
            </div>
          </div>
          <CardDescription>
            Configure how files are ingested and stored for retrieval. Edit in Langflow for full
            control.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="emb-provider">Embedding provider</Label>
            <select
              id="emb-provider"
              value={knowledge.embedding_provider}
              onChange={(e) => {
                const p = e.target.value;
                setKnowledge((k) => ({
                  ...k,
                  embedding_provider: p,
                  embedding_model: "",
                }));
              }}
              className="flex h-9 w-[180px] rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">Select provider</option>
              {EMBEDDING_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="emb-model" className="font-medium">
              Embedding model <span className="text-destructive">*</span>
            </Label>
            <p className="text-sm text-muted-foreground">
              Model used for knowledge ingest and retrieval
            </p>
            {embeddingModels.length > 0 ? (
              <select
                id="emb-model"
                value={knowledge.embedding_model}
                onChange={(e) =>
                  handleEmbeddingModelChange(knowledge.embedding_provider, e.target.value)
                }
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select model</option>
                {embeddingModels.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label || m.value}
                    {m.default ? " (default)" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id="emb-model"
                className="w-full"
                value={knowledge.embedding_model}
                onChange={(e) =>
                  setKnowledge((k) => ({ ...k, embedding_model: e.target.value }))
                }
                placeholder={getEmbeddingModelPlaceholder()}
                disabled={!knowledge.embedding_provider}
              />
            )}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="chunk-size">Chunk size</Label>
              <div className="flex items-center gap-2">
                <div className="relative flex flex-1">
                  <Input
                    id="chunk-size"
                    type="number"
                    min={1}
                    value={knowledge.chunk_size}
                    onChange={(e) =>
                      setKnowledge((k) => ({
                        ...k,
                        chunk_size: Number(e.target.value) || 0,
                      }))
                    }
                    className="pr-16 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                  />
                  <span className="absolute right-10 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                    characters
                  </span>
                  <div className="absolute right-1 top-1/2 -translate-y-1/2 flex flex-col gap-px">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4"
                      onClick={() =>
                        setKnowledge((k) => ({ ...k, chunk_size: Math.max(1, k.chunk_size + 1) }))
                      }
                    >
                      <Plus className="h-3 w-3" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4"
                      onClick={() =>
                        setKnowledge((k) => ({
                          ...k,
                          chunk_size: Math.max(1, k.chunk_size - 1),
                        }))
                      }
                    >
                      <Minus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="chunk-overlap">Chunk overlap</Label>
              <div className="flex items-center gap-2">
                <div className="relative flex flex-1">
                  <Input
                    id="chunk-overlap"
                    type="number"
                    min={0}
                    value={knowledge.chunk_overlap}
                    onChange={(e) =>
                      setKnowledge((k) => ({
                        ...k,
                        chunk_overlap: Math.max(0, Number(e.target.value) || 0),
                      }))
                    }
                    className="pr-16 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                  />
                  <span className="absolute right-10 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
                    characters
                  </span>
                  <div className="absolute right-1 top-1/2 -translate-y-1/2 flex flex-col gap-px">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4"
                      onClick={() =>
                        setKnowledge((k) => ({
                          ...k,
                          chunk_overlap: Math.max(0, k.chunk_overlap + 1),
                        }))
                      }
                    >
                      <Plus className="h-3 w-3" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-4 w-4"
                      onClick={() =>
                        setKnowledge((k) => ({
                          ...k,
                          chunk_overlap: Math.max(0, k.chunk_overlap - 1),
                        }))
                      }
                    >
                      <Minus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="space-y-0">
            <div className="flex items-center justify-between py-3 border-b border-border">
              <div className="flex-1">
                <Label htmlFor="table-structure" className="text-base font-medium cursor-pointer">
                  Table Structure
                </Label>
                <div className="text-sm text-muted-foreground">
                  Capture table structure during ingest.
                </div>
              </div>
              <Switch
                id="table-structure"
                checked={knowledge.table_structure}
                onCheckedChange={(v) =>
                  setKnowledge((k) => ({ ...k, table_structure: v }))
                }
              />
            </div>
            <div className="flex items-center justify-between py-3 border-b border-border">
              <div className="flex-1">
                <Label htmlFor="ocr" className="text-base font-medium cursor-pointer">
                  OCR
                </Label>
                <div className="text-sm text-muted-foreground">
                  Extracts text from images/PDFs. Ingest is slower when enabled.
                </div>
              </div>
              <Switch
                id="ocr"
                checked={knowledge.ocr}
                onCheckedChange={(v) => setKnowledge((k) => ({ ...k, ocr: v }))}
              />
            </div>
            <div className="flex items-center justify-between py-3">
              <div className="flex-1">
                <Label htmlFor="picture-descriptions" className="text-base font-medium cursor-pointer">
                  Picture Descriptions
                </Label>
                <div className="text-sm text-muted-foreground">
                  Adds captions for images. Ingest is slower when enabled.
                </div>
              </div>
              <Switch
                id="picture-descriptions"
                checked={knowledge.picture_descriptions}
                onCheckedChange={(v) =>
                  setKnowledge((k) => ({ ...k, picture_descriptions: v }))
                }
              />
            </div>
          </div>
          <Button onClick={saveKnowledgeSettings} disabled={savingKnowledge}>
            {savingKnowledge ? "Saving..." : "Save Knowledge Settings"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <KnowledgeSettingsApp />
  </StrictMode>
);