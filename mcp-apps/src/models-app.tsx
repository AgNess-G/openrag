/**
 * OpenRAG Models MCP App - list and select LLM/embedding models per provider.
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
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import "../globals.css";

const PROVIDERS = ["openai", "anthropic", "ollama", "watsonx"] as const;

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
        const textContent = result.content?.find((c) => c.type === "text")?.text;
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
        const textContent = result.content?.find((c) => c.type === "text")?.text;
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
    try {
      await app.callServerTool({
        name: "openrag_update_settings",
        arguments: { llm_model: selectedLlm },
      });
    } catch (e) {
      setError(String(e));
    }
  }, [app, selectedLlm]);

  const applyEmbedding = useCallback(async () => {
    if (!app || !selectedEmbedding) return;
    try {
      await app.callServerTool({
        name: "openrag_update_settings",
        arguments: { embedding_model: selectedEmbedding },
      });
    } catch (e) {
      setError(String(e));
    }
  }, [app, selectedEmbedding]);

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
              <CardTitle className="text-base">Language models</CardTitle>
              <CardDescription>Select the LLM for chat.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Select value={selectedLlm} onValueChange={setSelectedLlm}>
                <SelectTrigger>
                  <SelectValue placeholder="Select language model" />
                </SelectTrigger>
                <SelectContent>
                  {(data.language_models || []).map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      <span className="flex items-center gap-2">
                        {m.label || m.value}
                        {m.default && (
                          <Badge variant="secondary" className="text-xs">
                            default
                          </Badge>
                        )}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button size="sm" variant="outline" onClick={applyLlm} disabled={!selectedLlm}>
                Apply as LLM
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Embedding models</CardTitle>
              <CardDescription>Select the embedding model for knowledge ingest.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Select value={selectedEmbedding} onValueChange={setSelectedEmbedding}>
                <SelectTrigger>
                  <SelectValue placeholder="Select embedding model" />
                </SelectTrigger>
                <SelectContent>
                  {(data.embedding_models || []).map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      <span className="flex items-center gap-2">
                        {m.label || m.value}
                        {m.default && (
                          <Badge variant="secondary" className="text-xs">
                            default
                          </Badge>
                        )}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
