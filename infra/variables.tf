variable "subscription_id" {
  type = string
}

variable "name" {
  type    = string
  default = "agent-gateway"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.name))
    error_message = "Use 3–20 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "api_image" {
  type        = string
  description = "Public image reference, preferably pinned to a digest."
}

variable "browser_image" {
  type        = string
  default     = ""
  description = "Public browser worker image. Required only when enable_browser is true."
}

variable "enable_browser" {
  type    = bool
  default = false
}

variable "api_token" {
  type      = string
  sensitive = true
  validation {
    condition     = length(var.api_token) >= 32
    error_message = "API token must contain at least 32 characters."
  }
}

variable "browser_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "allowed_domains" {
  type    = list(string)
  default = ["example.com", "api.search.brave.com"]
  validation {
    condition     = length(var.allowed_domains) > 0 && alltrue([for domain in var.allowed_domains : can(regex("^[a-z0-9]+([.-][a-z0-9]+)*$", domain))])
    error_message = "Use explicit lowercase ASCII domain names."
  }
}

variable "client_cidrs" {
  type        = list(string)
  description = "Corporate public IPv4 egress ranges allowed to call the gateway."
  validation {
    condition     = length(var.client_cidrs) > 0 && alltrue([for cidr in var.client_cidrs : can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"])
    error_message = "Provide explicit corporate IPv4 CIDRs; 0.0.0.0/0 is not allowed."
  }
}

variable "search_provider" {
  type    = string
  default = "none"
  validation {
    condition     = contains(["none", "brave"], var.search_provider)
    error_message = "Search provider must be none or brave."
  }
}

variable "search_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "api_max_replicas" {
  type    = number
  default = 2
  validation {
    condition     = var.api_max_replicas >= 1 && var.api_max_replicas <= 10 && floor(var.api_max_replicas) == var.api_max_replicas
    error_message = "Use an integer from 1 to 10."
  }
}

variable "cache_ttl_seconds" {
  type    = number
  default = 60
  validation {
    condition     = var.cache_ttl_seconds >= 0 && var.cache_ttl_seconds <= 3600 && floor(var.cache_ttl_seconds) == var.cache_ttl_seconds
    error_message = "Cache TTL must be an integer from 0 to 3600."
  }
}
