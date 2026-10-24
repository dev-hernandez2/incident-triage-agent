{{- define "triage-agent.secretName" -}}
{{- if .Values.existingSecretName }}
{{- .Values.existingSecretName }}
{{- else }}
{{- printf "%s-secrets" .Release.Name }}
{{- end }}
{{- end }}

{{- define "triage-agent.modelForTier" -}}
{{- if eq .Values.models.tier "default" }}
{{- .Values.models.default }}
{{- else }}
{{- .Values.models.cheap }}
{{- end }}
{{- end }}
