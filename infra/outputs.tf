output "gateway_ip" {
  value = azurerm_public_ip.gateway.ip_address
}

output "deployment" {
  value = {
    admin_user = var.admin_user
    api_subnet = local.api_subnet
    apis = [for key, index in local.api_nodes : {
      name = "api-${key}"
      host = azurerm_public_ip.api[key].ip_address
    }]
    proxies = [for key, node in local.proxy_nodes : {
      name        = "proxy-${key}"
      host        = azurerm_public_ip.proxy["${key}-0"].ip_address
      private_ips = node.ips
      public_ips  = [for j, ip in node.ips : azurerm_public_ip.proxy["${key}-${j}"].ip_address]
    }]
  }
}
