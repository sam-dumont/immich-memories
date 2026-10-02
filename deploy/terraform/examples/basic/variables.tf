variable "image_tag" {
  description = "App release tag without the v prefix"
  type        = string
}

variable "immich_url" {
  description = "URL of your Immich instance"
  type        = string
}

variable "immich_api_key" {
  description = "Immich API key"
  type        = string
  sensitive   = true
}

variable "llm_base_url" {
  description = "Optional text reader endpoint; enable with IMMICH_MEMORIES_LLM__ENABLED in env"
  type        = string
  default     = ""
}

variable "llm_model" {
  description = "Text reader model name served at llm_base_url"
  type        = string
  default     = ""
}

variable "llm_api_key" {
  description = "API key for llm_base_url"
  type        = string
  default     = ""
  sensitive   = true
}

variable "gpu_enabled" {
  description = "Schedule on NVIDIA GPU nodes"
  type        = bool
  default     = false
}
