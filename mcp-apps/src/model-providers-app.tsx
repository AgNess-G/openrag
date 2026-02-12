/**
 * OpenRAG Model Providers MCP App - Configure API keys and endpoints.
 */
import { useApp } from "@modelcontextprotocol/ext-apps/react";
import { StrictMode, useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Card,
  CardContent,
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
import AnthropicLogo from "@/components/icons/anthropic-logo";
import IBMLogo from "@/components/icons/ibm-logo";
import OllamaLogo from "@/components/icons/ollama-logo";
import OpenAILogo from "@/components/icons/openai-logo";

import "../globals.css";

const PROVIDER_ORDER: ("openai" | "ollama" | "watsonx" | "anthropic")[] = ["openai", "ollama", "watsonx", "anthropic"];

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

const PROVIDER_NAMES: Record<string, string> = {
  openai: "OpenAI",
  ollama: "Ollama",
  watsonx: "IBM watsonx.ai",
  anthropic: "Anthropic",
};

const PROVIDER_LOGOS: Record<string, React.ComponentType<{ className?: string }>> = {
  openai: OpenAILogo,
  ollama: OllamaLogo,
  watsonx: IBMLogo,
  anthropic: AnthropicLogo,
};

function ModelProvidersApp() {
  const [providers, setProviders] = useState<ProvidersState>({});
  const [providerModal, setProviderModal] = useState<string | null>(null);
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
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { app, error: appError } = useApp({
    appInfo: { name: "OpenRAG Model Providers", version: "1.0.0" },
    capabilities: {},
    onAppCreated: (a) => {
      a.ontoolresult = async (result) => {
        const textContent = getToolResultText(result);
        if (!textContent) return;
        try {
          const data = JSON.parse(textContent);
          if (data.openai || data.anthropic || data.watsonx || data.ollama) {
            setProviders(data);
          }
          setError(null);
        } catch {
          setError("Failed to parse providers");
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
        name: "openrag_get_model_providers",
        arguments: {},
      });
      const textContent = getToolResultText(result);
      if (textContent) {
        const data = JSON.parse(textContent);
        setProviders(data);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRefreshing(false);
    }
  }, [app]);

  const updateProviders = useCallback(
    async (args: Record<string, unknown>) => {
      if (!app) return { error: null };
      try {
        const result = await app.callServerTool({
          name: "openrag_update_model_providers",
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
    async (provider: string) => {
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
        const { error: err } = await updateProviders(args);
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
    [app, providerForm, updateProviders, refresh]
  );

  useEffect(() => {
    if (app) {
      refresh();
    }
  }, [app, refresh]);

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

      {/* Provider modals - identical to settings-app */}
      <Dialog open={providerModal === "openai"} onOpenChange={(o) => !o && setProviderModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                <OpenAILogo className="text-black" />
              </div>
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
                className="w-full"
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
            <DialogTitle className="flex items-center gap-3">
              <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                <AnthropicLogo className="text-black" />
              </div>
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
                className="w-full"
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
            <DialogTitle className="flex items-center gap-3">
              <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                <OllamaLogo className="text-black" />
              </div>
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
                className="w-full"
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
            <DialogTitle className="flex items-center gap-3">
              <div className="w-8 h-8 rounded flex items-center justify-center bg-white border">
                <IBMLogo className="text-black" />
              </div>
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
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
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
                className="w-full"
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
                className="w-full"
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
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ModelProvidersApp />
  </StrictMode>
);