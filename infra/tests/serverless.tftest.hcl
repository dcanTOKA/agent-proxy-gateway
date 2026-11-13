mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  api_token       = "test-api-token-at-least-32-characters-long"
  api_image       = "ghcr.io/example/api:0.2.0"
  client_cidrs    = ["203.0.113.20/32"]
}

run "fetch_only" {
  command = plan
  assert {
    condition     = azurerm_container_app.api.template[0].min_replicas == 0
    error_message = "API must scale to zero."
  }
  assert {
    condition     = length(azurerm_container_app.browser) == 0
    error_message = "Browser must be optional and disabled by default."
  }
  assert {
    condition     = azurerm_container_app.api.template[0].container[0].cpu == 0.25
    error_message = "API must use a small Consumption allocation."
  }
}

run "optional_browser" {
  command = plan
  variables {
    enable_browser = true
    browser_token  = "test-worker-token-at-least-32-characters-long"
    browser_image  = "ghcr.io/example/browser:0.2.0"
  }
  assert {
    condition     = azurerm_container_app.browser[0].template[0].min_replicas == 0 && azurerm_container_app.browser[0].template[0].max_replicas == 1
    error_message = "Browser must scale to zero and cap the number of replicas."
  }
  assert {
    condition     = azurerm_container_app.browser[0].ingress[0].external_enabled == false
    error_message = "Browser must not be publicly accessible."
  }
}
