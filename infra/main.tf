resource "azurerm_resource_group" "main" {
  name     = var.name
  location = var.location
}

resource "azurerm_container_app_environment" "main" {
  name                = var.name
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  logs_destination    = "azure-monitor"
}

resource "azurerm_container_app" "browser" {
  count                        = var.enable_browser ? 1 : 0
  name                         = "${var.name}-browser"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  lifecycle {
    precondition {
      condition     = var.browser_image != "" && length(var.browser_token) >= 32 && var.browser_token != var.api_token
      error_message = "Browser requires an image and a distinct token of at least 32 characters."
    }
  }

  secret {
    name  = "worker-token"
    value = var.browser_token
  }

  template {
    min_replicas = 0
    max_replicas = 1
    http_scale_rule {
      name                = "browser-requests"
      concurrent_requests = "1"
    }
    container {
      name   = "browser"
      image  = var.browser_image
      cpu    = 1.0
      memory = "2Gi"
      env {
        name        = "GATEWAY_API_TOKEN"
        secret_name = "worker-token"
      }
      env {
        name  = "GATEWAY_ALLOWED_DOMAINS"
        value = jsonencode(var.allowed_domains)
      }
    }
  }

  ingress {
    external_enabled = false
    target_port      = 8000
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app" "api" {
  name                         = "${var.name}-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"

  secret {
    name  = "api-token"
    value = var.api_token
  }
  secret {
    name  = "search-key"
    value = var.search_api_key != "" ? var.search_api_key : "disabled"
  }
  secret {
    name  = "browser-token"
    value = var.browser_token != "" ? var.browser_token : "disabled"
  }

  lifecycle {
    precondition {
      condition     = var.search_provider == "none" || (var.search_api_key != "" && contains(var.allowed_domains, "api.search.brave.com"))
      error_message = "Brave search requires a key and api.search.brave.com in allowed_domains."
    }
  }

  template {
    min_replicas = 0
    max_replicas = var.api_max_replicas
    http_scale_rule {
      name                = "api-requests"
      concurrent_requests = "10"
    }
    container {
      name   = "api"
      image  = var.api_image
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name        = "GATEWAY_API_TOKEN"
        secret_name = "api-token"
      }
      env {
        name  = "GATEWAY_ALLOWED_DOMAINS"
        value = jsonencode(var.allowed_domains)
      }
      env {
        name  = "GATEWAY_SEARCH_PROVIDER"
        value = var.search_provider
      }
      env {
        name        = "GATEWAY_SEARCH_API_KEY"
        secret_name = "search-key"
      }
      env {
        name  = "GATEWAY_BROWSER_URL"
        value = var.enable_browser ? "https://${azurerm_container_app.browser[0].ingress[0].fqdn}" : ""
      }
      env {
        name        = "GATEWAY_BROWSER_TOKEN"
        secret_name = "browser-token"
      }
      env {
        name  = "GATEWAY_CACHE_TTL_SECONDS"
        value = tostring(var.cache_ttl_seconds)
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "http"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
    dynamic "ip_security_restriction" {
      for_each = toset(var.client_cidrs)
      content {
        name             = "corporate-${index(var.client_cidrs, ip_security_restriction.value)}"
        action           = "Allow"
        ip_address_range = ip_security_restriction.value
      }
    }
  }
}
