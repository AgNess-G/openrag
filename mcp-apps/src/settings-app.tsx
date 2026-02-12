/**
 * OpenRAG Settings MCP App - reuses frontend shadcn/ui components.
 * Matches OpenRAG Settings design: Model Providers (with setup modals),
 * Agent (language model auto-save, instructions with Save), Knowledge Ingest.
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
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import AnthropicLogo from "@/components/icons/anthropic-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";

import "../globals.css";

const LLM_PROVIDERS = ["openai", "anthropic", "ollama", "watsonx"] as const;
const EMBEDDING_PROVIDERS = ["openai", "ollama", "watsonx"] as const;
type ProviderKey = (typeof LLM_PROVIDERS)[number];

const PROVIDER_ORDER: ProviderKey[] = ["openai", "ollama", "watsonx", "anthropic"];

const WATSONX_ENDPOINTS = [
  "https://us-south.ml.cloud.ibm.com",
  "https://eu-de.ml.cloud.ibm.com",
  "https://eu-gb.ml.cloud.ibm.com",
  "https://au-syd.ml.cloud.ibm.com",
  "https://jp-tok.ml.cloud.ibm.com",
  "https://ca-tor.ml.cloud.ibm.com",
];

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

interface ProviderInfo {
  configured: boolean;
  endpoint?: string | null;
  project_id?: string | null;
}

interface ProvidersState {
  openai?: ProviderInfo;
  anthropic?: ProviderInfo;
  watsonx?: ProviderInfo;
  ollama?: ProviderInfo;
}

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
  chunk_size: 1024,
  chunk_overlap: 50,
  table_structure: true,
  ocr: false,
  picture_descriptions: false,
};

const PROVIDER_NAMES: Record<ProviderKey, string> = {
  openai: "OpenAI",
  ollama: "Ollama",
  watsonx: "IBM watsonx.ai",
  anthropic: "Anthropic",
};

const PROVIDER_LOGOS: Record<ProviderKey, React.ComponentType<{ className?: string }>> = {
  openai: OpenAILogo,
  ollama: OllamaLogo,
  watsonx: IBMLogo,
  anthropic: AnthropicLogo,
};

function SettingsApp() {
  const [providers, setProviders] = useState<ProvidersState>({});
  const [agent, setAgent] = useState<AgentSettings>(DEFAULT_AGENT);
  const [knowledge, setKnowledge] = useState<KnowledgeSettings>(DEFAULT_KNOWLEDGE);
  const [providerModal, setProviderModal] = useState<ProviderKey | null>(null);
  const [providerForm, setProviderForm] = useState<{
    openai: { apiKey: string };
    anthropic: { apiKey: string };
    ollama: { endpoint: string };
    watsonx: { endpoint: string; apiKey: string; projectId: string };
  }>({
    openai: { apiKey: "" },
    anthropic: { apiKey: "" },
    ollama: { endpoint: "http://localhost:11434" },
    watsonx: {
      endpoint: "https://us-south.ml.cloud.ibm.com",
      apiKey: "",
      projectId: "",
    },
  });
  const [saving, setSaving] = useState(false);
  const [savingInstructions, setSavingInstructions] = useState(false);
  const [savingKnowledge, setSavingKnowledge] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [llmModels, setLlmModels] = useState<ModelOption[]>([]);
  const [embeddingModels, setEmbeddingModels] = useState<ModelOption[]>([]);
  const [loadingLlmModels, setLoadingLlmModels] = useState(false);
  const [loadingEmbeddingModels, setLoadingEmbeddingModels] = useState(false);

  const { app, error: appError } = useApp({
    appInfo: { name: "OpenRAG Settings", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (a) => {
      a.ontoolresult = async (result) => {
        const textContent = getToolResultText(result);
        if (!textContent) return;
        try {
          const data = JSON.parse(textContent);
          if (data.agent) setAgent((prev) => ({ ...prev, ...data.agent }));
          if (data.knowledge) setKnowledge((prev) => ({ ...prev, ...data.knowledge }));
          if (data.providers) setProviders(data.providers);
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
      const textContent = getToolResultText(result);
      if (textContent) {
        const data = JSON.parse(textContent);
        if (data.agent) setAgent((prev) => ({ ...prev, ...data.agent }));
        if (data.knowledge) setKnowledge((prev) => ({ ...prev, ...data.knowledge }));
        if (data.providers) setProviders(data.providers);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRefreshing(false);
    }
  }, [app]);

  const updateSettings = useCallback(
    async (args: Record<string, unknown>) => {
      if (!app) return { error: null };
      try {
        const result = await app.callServerTool({
          name: "openrag_update_settings",
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

  const saveProviderModal = useCallback(
    async (provider: ProviderKey) => {
      if (!app) return;
      setSaving(true);
      setError(null);
      try {
        let args: Record<string, string> = {};
        if (provider === "openai") {
          args = { openai_api_key: providerForm.openai.apiKey };
        } else if (provider === "anthropic") {
          args = { anthropic_api_key: providerForm.anthropic.apiKey };
        } else if (provider === "ollama") {
          args = { ollama_endpoint: providerForm.ollama.endpoint };
        } else if (provider === "watsonx") {
          args = {
            watsonx_api_key: providerForm.watsonx.apiKey,
            watsonx_endpoint: providerForm.watsonx.endpoint,
            watsonx_project_id: providerForm.watsonx.projectId,
          };
        }
        const { error: err } = await updateSettings(args);
        if (err) setError(err);
        else {
          setProviderModal(null);
          await refresh();
        }
      } catch (e) {
        setError(String(e));
      } finally {
        setSaving(false);
      }
    },
    [app, providerForm, updateSettings, refresh]
  );

  const saveAgentInstructions = useCallback(async () => {
    setSavingInstructions(true);
    setError(null);
    try {
      const { error: err } = await updateSettings({ system_prompt: agent.system_prompt });
      if (err) setError(err);
    } finally {
      setSavingInstructions(false);
    }
  }, [agent.system_prompt, updateSettings]);

  const saveKnowledgeSettings = useCallback(async () => {
    setSavingKnowledge(true);
    setError(null);
    try {
      const { error: err } = await updateSettings({
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
  }, [knowledge, updateSettings]);

  const handleLlmModelChange = useCallback(
    async (llmProvider: string, llmModel: string) => {
      setAgent((a) => ({ ...a, llm_provider: llmProvider, llm_model: llmModel }));
      if (!llmModel) return;
      const { error: err } = await updateSettings({
        llm_provider: llmProvider,
        llm_model: llmModel,
      });
      if (err) setError(err);
    },
    [updateSettings]
  );

  const handleEmbeddingModelChange = useCallback(
    async (embeddingProvider: string, embeddingModel: string) => {
      setKnowledge((k) => ({
        ...k,
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel,
      }));
      if (!embeddingModel) return;
      const { error: err } = await updateSettings({
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel,
      });
      if (err) setError(err);
    },
    [updateSettings]
  );

  function getLlmModelPlaceholder(): string {
    if (loadingLlmModels) return "Loading models...";
    if (agent.llm_provider) return "No language models detected. Configure a provider first.";
    return "Select provider first";
  }

  function getEmbeddingModelPlaceholder(): string {
    if (loadingEmbeddingModels) return "Loading models...";
    if (knowledge.embedding_provider)
      return "No embedding models detected. Configure a provider first.";
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
    if (app) refresh();
  }, [app]);

  useEffect(() => {
    if (app && agent.llm_provider) loadLlmModels(agent.llm_provider);
    else setLlmModels([]);
  }, [app, agent.llm_provider, loadLlmModels]);

  useEffect(() => {
    if (app && knowledge.embedding_provider) loadEmbeddingModels(knowledge.embedding_provider);
    else setEmbeddingModels([]);
  }, [app, knowledge.embedding_provider, loadEmbeddingModels]);

  useEffect(() => {
    if (providerModal === "ollama" && providers.ollama?.endpoint) {
      setProviderForm((f) => ({
        ...f,
        ollama: { endpoint: providers.ollama!.endpoint || "http://localhost:11434" },
      }));
    }
    if (providerModal === "watsonx" && providers.watsonx) {
      setProviderForm((f) => ({
        ...f,
        watsonx: {
          ...f.watsonx,
          endpoint: providers.watsonx!.endpoint || "https://us-south.ml.cloud.ibm.com",
          projectId: providers.watsonx!.project_id || "",
        },
      }));
    }
  }, [providerModal, providers]);

  if (appError) return <div className="text-destructive p-4">Error: {appError.message}</div>;
  if (!app) return <div className="p-4 text-muted-foreground">Connecting...</div>;

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Model Providers */}
      <div>
        <h2 className="text-lg font-semibold tracking-tight mb-2">Model Providers</h2>
        <div className="grid gap-6 xs:grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
          {PROVIDER_ORDER.map((key) => {
            const Logo = PROVIDER_LOGOS[key];
            const name = PROVIDER_NAMES[key];
            const isConfigured = providers[key]?.configured ?? false;
            return (
              <Card key={key} className="relative flex flex-col">
                <CardHeader>
                  <div className="flex flex-col gap-3">
                    <div className="w-8 h-8 rounded flex items-center justify-center border bg-white">
                      <Logo className={isConfigured ? "text-black" : "text-muted-foreground"} />
                    </div>
                    <CardTitle className="text-base">{name}</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="flex-1 flex flex-col justify-end">
                  <Button
                    variant="outline"
                    onClick={() => setProviderModal(key)}
                  >
                    {isConfigured ? "Edit Setup" : "Configure"}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Provider modals */}
      <Dialog open={providerModal === "openai"} onOpenChange={(o) => !o && setProviderModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <OpenAILogo className="h-5 w-5" />
              OpenAI Setup
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="openai-api-key" className="font-medium">
                OpenAI API key <span className="text-destructive">*</span>
              </Label>
              <p className="text-sm text-muted-foreground">The API key for your OpenAI account</p>
              <Input
                id="openai-api-key"
                type="password"
                placeholder="sk-..."
                value={providerForm.openai.apiKey}
                onChange={(e) =>
                  setProviderForm((f) => ({
                    ...f,
                    openai: { ...f.openai, apiKey: e.target.value },
                  }))
                }
              />
            </div>
            <p className="text-sm text-muted-foreground">
              Configure language and embedding models in the Settings page after saving your API
              key.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProviderModal(null)}>
              Cancel
            </Button>
            <Button onClick={() => saveProviderModal("openai")} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={providerModal === "anthropic"} onOpenChange={(o) => !o && setProviderModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AnthropicLogo className="h-5 w-5" />
              Anthropic Setup
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="anthropic-api-key" className="font-medium">
                Anthropic API key <span className="text-destructive">*</span>
              </Label>
              <p className="text-sm text-muted-foreground">
                The API key for your Anthropic account
              </p>
              <Input
                id="anthropic-api-key"
                type="password"
                placeholder="sk-ant-..."
                value={providerForm.anthropic.apiKey}
                onChange={(e) =>
                  setProviderForm((f) => ({
                    ...f,
                    anthropic: { ...f.anthropic, apiKey: e.target.value },
                  }))
                }
              />
            </div>
            <p className="text-sm text-muted-foreground">
              Configure language models in the Settings page after saving your API key. Note:
              Anthropic does not provide embedding models.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProviderModal(null)}>
              Cancel
            </Button>
            <Button onClick={() => saveProviderModal("anthropic")} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={providerModal === "ollama"} onOpenChange={(o) => !o && setProviderModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <OllamaLogo className="h-5 w-5" />
              Ollama Setup
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ollama-endpoint" className="font-medium">
                Ollama Base URL <span className="text-destructive">*</span>
              </Label>
              <p className="text-sm text-muted-foreground">Base URL of your Ollama server</p>
              <Input
                id="ollama-endpoint"
                type="text"
                placeholder="http://localhost:11434"
                value={providerForm.ollama.endpoint}
                onChange={(e) =>
                  setProviderForm((f) => ({
                    ...f,
                    ollama: { ...f.ollama, endpoint: e.target.value },
                  }))
                }
              />
            </div>
            <p className="text-sm text-muted-foreground">
              Configure language and embedding models in the Settings page after saving your
              endpoint.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProviderModal(null)}>
              Cancel
            </Button>
            <Button onClick={() => saveProviderModal("ollama")} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={providerModal === "watsonx"} onOpenChange={(o) => !o && setProviderModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <IBMLogo className="h-5 w-5 text-[#1063FE]" />
              IBM watsonx.ai Setup
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="watsonx-endpoint" className="font-medium">
                watsonx.ai API Endpoint <span className="text-destructive">*</span>
              </Label>
              <p className="text-sm text-muted-foreground">Base URL of the API</p>
              <select
                id="watsonx-endpoint"
                value={providerForm.watsonx.endpoint}
                onChange={(e) =>
                  setProviderForm((f) => ({
                    ...f,
                    watsonx: { ...f.watsonx, endpoint: e.target.value },
                  }))
                }
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
              >
                {WATSONX_ENDPOINTS.map((ep) => (
                  <option key={ep} value={ep}>
                    {ep}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="watsonx-project-id" className="font-medium">
                watsonx Project ID <span className="text-destructive">*</span>
              </Label>
              <p className="text-sm text-muted-foreground">Project ID for the model</p>
              <Input
                id="watsonx-project-id"
                type="text"
                placeholder="your-project-id"
                value={providerForm.watsonx.projectId}
                onChange={(e) =>
                  setProviderForm((f) => ({
                    ...f,
                    watsonx: { ...f.watsonx, projectId: e.target.value },
                  }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="watsonx-api-key" className="font-medium">
                watsonx API key <span className="text-destructive">*</span>
              </Label>
              <p className="text-sm text-muted-foreground">API key to access watsonx.ai</p>
              <Input
                id="watsonx-api-key"
                type="password"
                placeholder="your-api-key"
                value={providerForm.watsonx.apiKey}
                onChange={(e) =>
                  setProviderForm((f) => ({
                    ...f,
                    watsonx: { ...f.watsonx, apiKey: e.target.value },
                  }))
                }
              />
            </div>
            <p className="text-sm text-muted-foreground">
              Configure language and embedding models in the Settings page after saving your
              credentials.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setProviderModal(null)}>
              Cancel
            </Button>
            <Button onClick={() => saveProviderModal("watsonx")} disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Agent */}
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
                className="flex h-9 w-full max-w-md rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
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
                className="max-w-md"
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

      {/* Knowledge Ingest */}
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
                className="flex h-9 w-full max-w-md rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
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
                className="max-w-md"
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
    <SettingsApp />
  </StrictMode>
);
