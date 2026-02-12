/**
 * OpenRAG Models MCP App - list and select LLM/embedding models per provider.
 * Uses native <select> for dropdowns so they work in MCP host iframes (no Radix portal).
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
import { Label } from "@/components/ui/label";

import "../globals.css";

const PROVIDERS = ["openai", "anthropic", "ollama", "watsonx"] as const;

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

interface ModelsData {
  language_models?: ModelOption[];
  embedding_models?: ModelOption[];
}

function ModelsApp() {
  const [provider, setProvider] = useState<string>("openai");
  const [data, setData] = useState<ModelsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedLlm, setSelectedLlm] = useState<string>("");
  const [selectedEmbedding, setSelectedEmbedding] = useState<string>("");

  const { app, error: appError } = useApp({
    appInfo: { name: "OpenRAG Models", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (app) => {
      app.ontoolresult = async (result) => {
        const textContent = getToolResultText(result);
        if (!textContent) return;
        try {
          const parsed = JSON.parse(textContent);
          if (parsed.error) {
            setError(parsed.error);
            setData(null);
          } else {
            setData(parsed);
            setError(null);
          }
        } catch {
          setError("Failed to parse model list");
          setData(null);
        }
      };
    },
  });

  const loadModels = useCallback(
    async (prov: string) => {
      if (!app) return;
      setLoading(true);
      setError(null);
      try {
        const result = await app.callServerTool({
          name: "openrag_list_models",
          arguments: { provider: prov },
        });
        const textContent = getToolResultText(result);
        if (textContent) {
          const parsed = JSON.parse(textContent);
          if (parsed.error) setError(parsed.error);
          else setData(parsed);
        }
      } catch (e) {
        setError(String(e));
      } finally {
        setLoading(false);
      }
    },
    [app]
  );

  useEffect(() => {
    if (app && provider) loadModels(provider);
  }, [app, provider]);

  const applyLlm = useCallback(async () => {
    if (!app || !selectedLlm) return;
    setError(null);
    try {
      await app.callServerTool({
        name: "openrag_update_settings",
        arguments: { llm_provider: provider, llm_model: selectedLlm },
      });
    } catch (e) {
      setError(String(e));
    }
  }, [app, provider, selectedLlm]);

  const applyEmbedding = useCallback(async () => {
    if (!app || !selectedEmbedding) return;
    setError(null);
    try {
      await app.callServerTool({
        name: "openrag_update_settings",
        arguments: {
          embedding_provider: provider,
          embedding_model: selectedEmbedding,
        },
      });
    } catch (e) {
      setError(String(e));
    }
  }, [app, provider, selectedEmbedding]);

  if (appError) return <div className="text-destructive p-4">Error: {appError.message}</div>;
  if (!app) return <div className="p-4 text-muted-foreground">Connecting...</div>;

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}
      <div className="space-y-2">
        <Label>Provider</Label>
        <div className="flex gap-2 flex-wrap">
          {PROVIDERS.map((p) => (
            <Button
              key={p}
              variant={provider === p ? "default" : "outline"}
              size="sm"
              onClick={() => setProvider(p)}
            >
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </Button>
          ))}
        </div>
      </div>

      {loading && <p className="text-sm text-muted-foreground">Loading models...</p>}

      {data && !loading && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Language model</CardTitle>
              <CardDescription>
                Model used for chat. Apply to save.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <Label htmlFor="llm-select" className="sr-only">
                Select language model
              </Label>
              <select
                id="llm-select"
                value={selectedLlm}
                onChange={(e) => setSelectedLlm(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select language model</option>
                {(data.language_models || []).map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label || m.value}
                    {m.default ? " (default)" : ""}
                  </option>
                ))}
              </select>
              <Button size="sm" variant="outline" onClick={applyLlm} disabled={!selectedLlm}>
                Apply as LLM
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Embedding model</CardTitle>
              <CardDescription>
                Model used for knowledge ingest and retrieval. Apply to save.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <Label htmlFor="emb-select" className="sr-only">
                Select embedding model
              </Label>
              <select
                id="emb-select"
                value={selectedEmbedding}
                onChange={(e) => setSelectedEmbedding(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select embedding model</option>
                {(data.embedding_models || []).map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label || m.value}
                    {m.default ? " (default)" : ""}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="outline"
                onClick={applyEmbedding}
                disabled={!selectedEmbedding}
              >
                Apply as embedding model
              </Button>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ModelsApp />
  </StrictMode>
);
