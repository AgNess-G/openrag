/**
 * OpenRAG Agent Settings MCP App - Configure LLM and system prompt.
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
import { Textarea } from "@/components/ui/textarea";

import "../globals.css";

const LLM_PROVIDERS = ["openai", "anthropic", "ollama", "watsonx"] as const;

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

const MAX_SYSTEM_PROMPT_CHARS = 4000;

interface AgentSettings {
  llm_provider: string;
  llm_model: string;
  system_prompt: string;
}

function AgentSettingsApp() {
  const [agent, setAgent] = useState<AgentSettings>({
    llm_provider: "",
    llm_model: "",
    system_prompt: "",
  });
  const [savingInstructions, setSavingInstructions] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [llmModels, setLlmModels] = useState<ModelOption[]>([]);
  const [loadingLlmModels, setLoadingLlmModels] = useState(false);

  const { app, error: appError } = useApp({
    appInfo: { name: "OpenRAG Agent Settings", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (a) => {
      a.ontoolresult = async (result) => {
        const textContent = getToolResultText(result);
        if (!textContent) return;
        try {
          const data = JSON.parse(textContent);
          if (data.llm_provider !== undefined || data.llm_model !== undefined || data.system_prompt !== undefined) {
            setAgent((prev) => ({ ...prev, ...data }));
          }
          setError(null);
        } catch {
          setError("Failed to parse agent settings");
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
        name: "openrag_get_agent_settings",
        arguments: {},
      });
      const textContent = getToolResultText(result);
      if (textContent) {
        const data = JSON.parse(textContent);
        setAgent((prev) => ({ ...prev, ...data }));
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRefreshing(false);
    }
  }, [app]);

  const updateAgentSettings = useCallback(
    async (args: Record<string, unknown>) => {
      if (!app) return { error: null };
      try {
        const result = await app.callServerTool({
          name: "openrag_update_agent_settings",
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

  const saveAgentInstructions = useCallback(async () => {
    setSavingInstructions(true);
    setError(null);
    try {
      const { error: err } = await updateAgentSettings({ system_prompt: agent.system_prompt });
      if (err) setError(err);
    } finally {
      setSavingInstructions(false);
    }
  }, [agent.system_prompt, updateAgentSettings]);

  const handleLlmModelChange = useCallback(
    async (llmProvider: string, llmModel: string) => {
      setAgent((a) => ({ ...a, llm_provider: llmProvider, llm_model: llmModel }));
      if (!llmModel) return;
      const { error: err } = await updateAgentSettings({
        llm_provider: llmProvider,
        llm_model: llmModel,
      });
      if (err) setError(err);
    },
    [updateAgentSettings]
  );

  function getLlmModelPlaceholder(): string {
    if (loadingLlmModels) return "Loading models...";
    if (agent.llm_provider) return "No language models detected. Configure a provider first.";
    return "Select provider first";
  }

  const loadLlmModels = useCallback(
    async (provider: string) => {
      if (!app || !provider) {
        setLlmModels([]);
        return;
      }
      setLoadingLlmModels(true);
      try {
        const result = await app.callServerTool({
          name: "openrag_list_models",
          arguments: { provider },
        });
        const textContent = getToolResultText(result);
        if (textContent) {
          const parsed = JSON.parse(textContent);
          if (!parsed.error && parsed.language_models) {
            setLlmModels(parsed.language_models);
          } else {
            setLlmModels([]);
          }
        } else {
          setLlmModels([]);
        }
      } catch {
        setLlmModels([]);
      } finally {
        setLoadingLlmModels(false);
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
    if (app && agent.llm_provider) loadLlmModels(agent.llm_provider);
    else setLlmModels([]);
  }, [app, agent.llm_provider, loadLlmModels]);

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
            <CardTitle className="text-lg">Agent</CardTitle>
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
            This Agent retrieves from your knowledge and generates chat responses. Edit in Langflow
            for full control.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label htmlFor="llm-provider" className="font-medium">
              Language model provider
            </Label>
            <select
              id="llm-provider"
              value={agent.llm_provider}
              onChange={(e) => {
                const p = e.target.value;
                setAgent((a) => ({ ...a, llm_provider: p, llm_model: "" }));
              }}
              className="flex h-9 w-[180px] rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">Select provider</option>
              {LLM_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {p.charAt(0).toUpperCase() + p.slice(1)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="llm-model" className="font-medium">
              Language model <span className="text-destructive">*</span>
            </Label>
            <p className="text-sm text-muted-foreground">Model used for chat</p>
            {llmModels.length > 0 ? (
              <select
                id="llm-model"
                value={agent.llm_model}
                onChange={(e) => handleLlmModelChange(agent.llm_provider, e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <option value="">Select model</option>
                {llmModels.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label || m.value}
                    {m.default ? " (default)" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                id="llm-model"
                className="w-full"
                value={agent.llm_model}
                onChange={(e) =>
                  setAgent((a) => ({ ...a, llm_model: e.target.value }))
                }
                placeholder={getLlmModelPlaceholder()}
                disabled={!agent.llm_provider}
              />
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="system-prompt" className="font-medium">
              Agent Instructions
            </Label>
            <Textarea
              id="system-prompt"
              value={agent.system_prompt}
              onChange={(e) => setAgent((a) => ({ ...a, system_prompt: e.target.value }))}
              placeholder="Enter your agent instructions here..."
              rows={6}
              className={`resize-none ${agent.system_prompt.length > MAX_SYSTEM_PROMPT_CHARS ? "!border-destructive focus:border-destructive" : ""}`}
            />
            <span
              className={`text-xs ${agent.system_prompt.length > MAX_SYSTEM_PROMPT_CHARS ? "text-destructive" : "text-muted-foreground"}`}
            >
              {agent.system_prompt.length}/{MAX_SYSTEM_PROMPT_CHARS} characters
            </span>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={refresh} disabled={refreshing}>
              {refreshing ? "Refreshing..." : "Refresh"}
            </Button>
            <Button
              size="sm"
              onClick={saveAgentInstructions}
              disabled={
                savingInstructions ||
                agent.system_prompt.length > MAX_SYSTEM_PROMPT_CHARS
              }
            >
              {savingInstructions ? "Saving..." : "Save Agent Instructions"}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AgentSettingsApp />
  </StrictMode>
);