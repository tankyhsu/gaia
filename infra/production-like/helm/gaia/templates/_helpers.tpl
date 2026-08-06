{{- define "gaia.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "gaia.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "gaia.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "gaia.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "gaia.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "gaia.selectorLabels" -}}
app.kubernetes.io/name: {{ include "gaia.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "gaia.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "gaia.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- required "serviceAccount.name is required when serviceAccount.create=false" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "gaia.secretName" -}}
{{- required "secrets.existingSecret is required; manage production credentials outside this chart" .Values.secrets.existingSecret }}
{{- end }}

{{- define "gaia.commonEnv" -}}
- name: GAIA_CONFIG_PATH
  value: /etc/gaia/gaia.yaml
- name: GAIA_PROJECT_ROOT
  value: /app
- name: GAIA_DEVTOOLS_ENABLED
  value: "false"
- name: PYTHONDONTWRITEBYTECODE
  value: "1"
- name: GAIA_POSTGRES_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "gaia.secretName" . }}
      key: {{ .Values.secrets.keys.postgresUrl }}
- name: GAIA_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "gaia.secretName" . }}
      key: {{ .Values.secrets.keys.postgresUrl }}
- name: GAIA_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "gaia.secretName" . }}
      key: {{ .Values.secrets.keys.apiKey }}
{{- if eq .Values.gaia.config.gaia.observability.provider "langfuse" }}
- name: LANGFUSE_PUBLIC_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "gaia.secretName" . }}
      key: {{ .Values.secrets.keys.langfusePublicKey }}
- name: LANGFUSE_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: {{ include "gaia.secretName" . }}
      key: {{ .Values.secrets.keys.langfuseSecretKey }}
{{- end }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "gaia.podTemplateMetadata" -}}
labels:
  {{- include "gaia.selectorLabels" .root | nindent 2 }}
  app.kubernetes.io/component: {{ .component }}
  {{- with .root.Values.podLabels }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
annotations:
  checksum/config: {{ toYaml .root.Values.gaia.config | sha256sum }}
  {{- with .root.Values.podAnnotations }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- end }}
