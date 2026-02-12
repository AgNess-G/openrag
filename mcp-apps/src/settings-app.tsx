/**
 * OpenRAG Settings MCP App - reuses frontend shadcn/ui components.
 */
import { useApp } from "@modelcontextprotocol/ext-apps/react";
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
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import "../globals.css";

const MAX_SYSTEM_PROMPT_CHARS = 4000;

interface AgentSettings {
  llm_provider: string;
  llm_model: string;
  system_prompt: string;
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

const DEFAULT_AGENT: AgentSettings = {
  llm_provider: "",
  llm_model: "",
  system_prompt: "",
};

const DEFAULT_KNOWLEDGE: KnowledgeSettings = {
  embedding_provider: "",
  embedding_model: "",
  chunk_size: 1000,
  chunk_overlap: 200,
  table_structure: false,
  ocr: false,
  picture_descriptions: false,
};

function SettingsApp() {
  const [agent, setAgent] = useState<AgentSettings>(DEFAULT_AGENT);
  const [knowledge, setKnowledge] = useState<KnowledgeSettings>(DEFAULT_KNOWLEDGE);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { app, error: appError } = useApp({
    appInfo: { name: "OpenRAG Settings", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (app) => {
      app.ontoolresult = async (result) => {
        const textContent = result.content?.find((c) => c.type === "text")?.text;
        if (!textContent) return;
        try {
          const data = JSON.parse(textContent);
          if (data.agent) setAgent((prev) => ({ ...prev, ...data.agent }));
          if (data.knowledge) setKnowledge((prev) => ({ ...prev, ...data.knowledge }));
          setError(null);
        } catch {
          setError("Failed to parse settings");
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
        name: "openrag_get_settings",
        arguments: {},
      });
      const textContent = result.content?.find((c) => c.type === "text")?.text;
      if (textContent) {
        const data = JSON.parse(textContent);
        if (data.agent) setAgent((prev) => ({ ...prev, ...data.agent }));
        if (data.knowledge) setKnowledge((prev) => ({ ...prev, ...data.knowledge }));
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRefreshing(false);
    }
  }, [app]);

  const save = useCallback(async () => {
    if (!app) return;
    setSaving(true);
    setError(null);
    try {
      const result = await app.callServerTool({
        name: "openrag_update_settings",
        arguments: {
          llm_provider: agent.llm_provider || undefined,
          llm_model: agent.llm_model || undefined,
          embedding_provider: knowledge.embedding_provider || undefined,
          embedding_model: knowledge.embedding_model || undefined,
          chunk_size: knowledge.chunk_size,
          chunk_overlap: knowledge.chunk_overlap,
          system_prompt: agent.system_prompt || undefined,
          table_structure: knowledge.table_structure,
          ocr: knowledge.ocr,
          picture_descriptions: knowledge.picture_descriptions,
        },
      });
      const textContent = result.content?.find((c) => c.type === "text")?.text;
      if (textContent) {
        const data = JSON.parse(textContent);
        if (data.error) setError(data.error);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }, [app, agent, knowledge]);

  useEffect(() => {
    if (app) refresh();
  }, [app]);

  if (appError) return <div className="text-destructive p-4">Error: {appError.message}</div>;
  if (!app) return <div className="p-4 text-muted-foreground">Connecting...</div>;

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
          {refreshing ? "Refreshing..." : "Refresh"}
        </Button>
        <Button size="sm" onClick={save} disabled={saving}>
          {saving ? "Saving..." : "Save settings"}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Agent</CardTitle>
          <CardDescription>
            This Agent retrieves from your knowledge and generates chat responses.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Language model</Label>
            <div className="flex gap-2">
              <Select
                value={agent.llm_provider}
                onValueChange={(v) => setAgent((a) => ({ ...a, llm_provider: v }))}
              >
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="openai">OpenAI</SelectItem>
                  <SelectItem value="anthropic">Anthropic</SelectItem>
                  <SelectItem value="ollama">Ollama</SelectItem>
                  <SelectItem value="watsonx">WatsonX</SelectItem>
                </SelectContent>
              </Select>
              <Input
                className="flex-1"
                value={agent.llm_model}
                onChange={(e) => setAgent((a) => ({ ...a, llm_model: e.target.value }))}
                placeholder="Model name"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Agent instructions</Label>
            <Textarea
              value={agent.system_prompt}
              onChange={(e) => setAgent((a) => ({ ...a, system_prompt: e.target.value }))}
              placeholder="Enter your agent instructions here..."
              rows={4}
              className="resize-none"
            />
            <span className="text-xs text-muted-foreground">
              {agent.system_prompt.length}/{MAX_SYSTEM_PROMPT_CHARS} characters
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Knowledge ingest</CardTitle>
          <CardDescription>
            Configure how files are ingested and stored for retrieval.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Embedding model</Label>
            <div className="flex gap-2">
              <Select
                value={knowledge.embedding_provider}
                onValueChange={(v) =>
                  setKnowledge((k) => ({ ...k, embedding_provider: v }))
                }
              >
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Provider" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="openai">OpenAI</SelectItem>
                  <SelectItem value="ollama">Ollama</SelectItem>
                  <SelectItem value="watsonx">WatsonX</SelectItem>
                </SelectContent>
              </Select>
              <Input
                className="flex-1"
                value={knowledge.embedding_model}
                onChange={(e) =>
                  setKnowledge((k) => ({ ...k, embedding_model: e.target.value }))
                }
                placeholder="Model name"
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Chunk size</Label>
              <Input
                type="number"
                min={1}
                value={knowledge.chunk_size}
                onChange={(e) =>
                  setKnowledge((k) => ({ ...k, chunk_size: Number(e.target.value) || 0 }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label>Chunk overlap</Label>
              <Input
                type="number"
                min={0}
                value={knowledge.chunk_overlap}
                onChange={(e) =>
                  setKnowledge((k) => ({
                    ...k,
                    chunk_overlap: Number(e.target.value) || 0,
                  }))
                }
              />
            </div>
          </div>
          <div className="space-y-0">
            <div className="flex items-center justify-between py-3 border-b border-border">
              <div className="flex-1">
                <Label className="text-base font-medium">Table structure</Label>
                <p className="text-sm text-muted-foreground">
                  Capture table structure during ingest.
                </p>
              </div>
              <Switch
                checked={knowledge.table_structure}
                onCheckedChange={(v) =>
                  setKnowledge((k) => ({ ...k, table_structure: v }))
                }
              />
            </div>
            <div className="flex items-center justify-between py-3 border-b border-border">
              <div className="flex-1">
                <Label className="text-base font-medium">OCR</Label>
                <p className="text-sm text-muted-foreground">
                  Extracts text from images/PDFs. Ingest is slower when enabled.
                </p>
              </div>
              <Switch
                checked={knowledge.ocr}
                onCheckedChange={(v) => setKnowledge((k) => ({ ...k, ocr: v }))}
              />
            </div>
            <div className="flex items-center justify-between py-3">
              <div className="flex-1">
                <Label className="text-base font-medium">Picture descriptions</Label>
                <p className="text-sm text-muted-foreground">
                  Adds captions for images. Ingest is slower when enabled.
                </p>
              </div>
              <Switch
                checked={knowledge.picture_descriptions}
                onCheckedChange={(v) =>
                  setKnowledge((k) => ({ ...k, picture_descriptions: v }))
                }
              />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SettingsApp />
  </StrictMode>
);
