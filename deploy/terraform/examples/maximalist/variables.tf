variable "kubeconfig_path" {
  description = "Path to kubeconfig file"
  type        = string
  default     = "~/.kube/config"
}

variable "kubeconfig_context" {
  description = "Kubeconfig context to use"
  type        = string
  default     = null
}

variable "namespace" {
  description = "Kubernetes namespace"
  type        = string
  default     = "immich-memories"
}

variable "image_tag" {
  description = "Container image tag (no `v` prefix)"
  type        = string
  default     = "latest"
}

# Immich
variable "immich_url" {
  description = "URL of your Immich instance"
  type        = string
}

variable "immich_api_key" {
  description = "Immich API key"
  type        = string
  sensitive   = true
}

# OIDC behind a TLS-terminating reverse proxy
variable "oidc_issuer_url" {
  description = "OIDC issuer, e.g. https://idp.example.com/realms/family"
  type        = string
}

variable "oidc_client_id" {
  description = "OIDC client ID"
  type        = string
}

variable "oidc_client_secret" {
  description = "OIDC client secret; empty for a public client"
  type        = string
  default     = ""
  sensitive   = true
}

variable "oidc_public_url" {
  description = "The externally reachable URL users type"
  type        = string
}

variable "oidc_trusted_proxies" {
  description = "The cluster's pod CIDR, IPv4 and IPv6 (kubectl get nodes -o wide, or your CNI's docs)"
  type        = list(string)
}

variable "oidc_allowed_emails" {
  description = "Who may sign in"
  type        = list(string)
  default     = []
}

# The render worker as a sidecar
variable "render_worker_token" {
  description = "Bearer token both containers share"
  type        = string
  sensitive   = true
}

# An LLM and ACE-Step on a LAN machine, e.g. an Apple Silicon Mac
variable "lan_llm_base_url" {
  description = "OpenAI-compatible endpoint on the LAN"
  type        = string
}

variable "lan_llm_model" {
  description = "Vision model name served at lan_llm_base_url"
  type        = string
}

variable "ace_step_api_url" {
  description = "ACE-Step 1.5 API server URL (acestep-api), in-cluster or on the same LAN machine"
  type        = string
}

variable "ace_step_api_key" {
  description = "ACE-Step API key, if the server requires one"
  type        = string
  default     = ""
  sensitive   = true
}

# Storage
variable "storage_class_name" {
  description = "Storage class for PVCs"
  type        = string
  default     = null
}
