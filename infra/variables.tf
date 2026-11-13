variable "subscription_id" {
  type = string
}

variable "name" {
  type    = string
  default = "agent-gateway"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.name))
    error_message = "Use 3–30 lowercase letters, digits and hyphens, starting with a letter."
  }
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "api_vm_count" {
  type    = number
  default = 1
  validation {
    condition     = var.api_vm_count >= 1 && var.api_vm_count <= 16 && floor(var.api_vm_count) == var.api_vm_count
    error_message = "API count must be an integer from 1 to 16."
  }
}

variable "proxy_vm_count" {
  type    = number
  default = 1
  validation {
    condition     = var.proxy_vm_count >= 1 && var.proxy_vm_count <= 16 && floor(var.proxy_vm_count) == var.proxy_vm_count
    error_message = "Proxy count must be an integer from 1 to 16."
  }
}

variable "proxy_ips_per_vm" {
  type    = number
  default = 1
  validation {
    condition     = var.proxy_ips_per_vm >= 1 && var.proxy_ips_per_vm <= 4 && floor(var.proxy_ips_per_vm) == var.proxy_ips_per_vm
    error_message = "Public IP count per proxy VM must be an integer from 1 to 4."
  }
}

variable "api_vm_size" {
  type    = string
  default = "Standard_B2s"
}

variable "proxy_vm_size" {
  type    = string
  default = "Standard_B2s"
}

variable "admin_user" {
  type    = string
  default = "azureuser"
}

variable "ssh_public_key" {
  type = string
}

variable "admin_cidrs" {
  type = list(string)
  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for cidr in var.admin_cidrs : can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"])
    error_message = "Provide explicit IPv4 admin CIDRs; 0.0.0.0/0 is not allowed."
  }
}

variable "client_cidrs" {
  type = list(string)
  validation {
    condition     = length(var.client_cidrs) > 0 && alltrue([for cidr in var.client_cidrs : can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"])
    error_message = "Provide explicit corporate IPv4 egress CIDRs; 0.0.0.0/0 is not allowed."
  }
}
