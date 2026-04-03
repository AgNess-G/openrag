{{/*
=============================================================================
OpenRAG Helm helpers
=============================================================================
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "openrag.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited.
*/}}
{{- define "openrag.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "openrag.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "openrag.labels" -}}
helm.sh/chart: {{ include "openrag.chart" . }}
{{ include "openrag.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels (stable — used in matchLabels; do not add mutable fields).
*/}}
{{- define "openrag.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openrag.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
ServiceAccount name.
*/}}
{{- define "openrag.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "openrag.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Secret name — use existingSecret if provided, else chart-managed secret.
*/}}
{{- define "openrag.secretName" -}}
{{- if .Values.backend.existingSecret }}
{{- .Values.backend.existingSecret }}
{{- else }}
{{- include "openrag.fullname" . }}-secrets
{{- end }}
{{- end }}

{{/*
=============================================================================
Component labels helpers
=============================================================================
*/}}

{{- define "openrag.backend.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{- define "openrag.backend.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: backend
{{- end }}

{{- define "openrag.frontend.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{- define "openrag.frontend.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: frontend
{{- end }}

{{- define "openrag.opensearch.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: opensearch
{{- end }}

{{- define "openrag.opensearch.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: opensearch
{{- end }}

{{- define "openrag.worker.labels" -}}
{{ include "openrag.labels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{- define "openrag.worker.selectorLabels" -}}
{{ include "openrag.selectorLabels" . }}
app.kubernetes.io/component: worker
{{- end }}

{{/*
=============================================================================
Image helpers
=============================================================================
*/}}

{{/*
Backend image (registry prefix + repository:tag).
*/}}
{{- define "openrag.backend.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .Values.image.backend.repository -}}
{{- $tag := .Values.image.backend.tag | default "latest" -}}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repo $tag }}
{{- else }}
{{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}

{{/*
Frontend image.
*/}}
{{- define "openrag.frontend.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .Values.image.frontend.repository -}}
{{- $tag := .Values.image.frontend.tag | default "latest" -}}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repo $tag }}
{{- else }}
{{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}

{{/*
OpenSearch image.
*/}}
{{- define "openrag.opensearch.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repo := .Values.image.opensearch.repository -}}
{{- $tag := .Values.image.opensearch.tag | default "latest" -}}
{{- if $registry }}
{{- printf "%s/%s:%s" $registry $repo $tag }}
{{- else }}
{{- printf "%s:%s" $repo $tag }}
{{- end }}
{{- end }}

{{/*
Worker image — falls back to backend image when not explicitly set.
*/}}
{{- define "openrag.worker.image" -}}
{{- if .Values.worker.image }}
{{- .Values.worker.image }}
{{- else }}
{{- include "openrag.backend.image" . }}
{{- end }}
{{- end }}

{{/*
=============================================================================
Service name helpers
=============================================================================
*/}}

{{- define "openrag.backend.serviceName" -}}
{{- include "openrag.fullname" . }}-backend
{{- end }}

{{- define "openrag.frontend.serviceName" -}}
{{- include "openrag.fullname" . }}-frontend
{{- end }}

{{- define "openrag.opensearch.serviceName" -}}
{{- include "openrag.fullname" . }}-opensearch
{{- end }}

{{/*
Redis host: internal sub-chart ClusterIP or external host.
*/}}
{{- define "openrag.redis.host" -}}
{{- if .Values.redis.enabled }}
{{- printf "%s-redis-master" (include "openrag.fullname" .) }}
{{- else }}
{{- .Values.redis_external.host }}
{{- end }}
{{- end }}

{{/*
Redis port.
*/}}
{{- define "openrag.redis.port" -}}
{{- if .Values.redis.enabled }}
{{- "6379" }}
{{- else }}
{{- .Values.redis_external.port | toString }}
{{- end }}
{{- end }}

{{/*
OpenSearch host: in-cluster service or external.
*/}}
{{- define "openrag.opensearch.host" -}}
{{- if .Values.opensearch.enabled }}
{{- include "openrag.opensearch.serviceName" . }}
{{- else }}
{{- .Values.opensearch_external.host }}
{{- end }}
{{- end }}

{{/*
OpenSearch port.
*/}}
{{- define "openrag.opensearch.port" -}}
{{- if .Values.opensearch.enabled }}
{{- "9200" }}
{{- else }}
{{- .Values.opensearch_external.port | toString }}
{{- end }}
{{- end }}

{{/*
=============================================================================
imagePullSecrets helper — merges global list.
=============================================================================
*/}}
{{- define "openrag.imagePullSecrets" -}}
{{- with .Values.global.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/*
=============================================================================
Shared env-from-secret block for components that need secrets.
=============================================================================
*/}}
{{- define "openrag.secretEnvFrom" -}}
- secretRef:
    name: {{ include "openrag.secretName" . }}
{{- end }}
