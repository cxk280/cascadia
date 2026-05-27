{{/*
Expand the name of the chart.
*/}}
{{- define "cascadia.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Fully-qualified app name. Truncated to 63 chars for k8s naming.
*/}}
{{- define "cascadia.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Common labels (Helm standard).
*/}}
{{- define "cascadia.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "cascadia.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: proxy
app.kubernetes.io/part-of: cascadia
{{- end -}}

{{/*
Selector labels (only those that identify a pod for a service).
*/}}
{{- define "cascadia.selectorLabels" -}}
app.kubernetes.io/name: {{ include "cascadia.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
ServiceAccount name.
*/}}
{{- define "cascadia.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "cascadia.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/*
Secret name (existing or chart-created).
*/}}
{{- define "cascadia.secretName" -}}
{{- if .Values.existingSecret -}}
{{- .Values.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "cascadia.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/*
Image reference (`repo:tag`).
*/}}
{{- define "cascadia.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{/*
Default soft anti-affinity that prefers spreading replicas across nodes by
hostname. Uses the templated app.kubernetes.io/name so `nameOverride:`
doesn't silently disable the spread by pointing the labelSelector at a
non-existent label value. Only emitted when the user hasn't set their own
`affinity:` in values.
*/}}
{{- define "cascadia.defaultAffinity" -}}
podAntiAffinity:
  preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        topologyKey: kubernetes.io/hostname
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: {{ include "cascadia.name" . }}
            app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
