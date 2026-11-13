resource "azurerm_network_security_group" "api" {
  name                = "${var.name}-api"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name

  security_rule {
    name                       = "CorporateHTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefixes    = var.client_cidrs
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "AdminSSH"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefixes    = var.admin_cidrs
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "HealthProbe"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8080"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "DenyOtherInbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_security_group" "proxy" {
  name                = "${var.name}-proxy"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  security_rule {
    name                       = "APIToSquid"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "3128-3131"
    source_address_prefix      = local.api_subnet
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "AdminSSH"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefixes    = var.admin_cidrs
    destination_address_prefix = "*"
  }
  security_rule {
    name                       = "DenyOtherInbound"
    priority                   = 4000
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "api" {
  subnet_id                 = azurerm_subnet.api.id
  network_security_group_id = azurerm_network_security_group.api.id
}

resource "azurerm_subnet_network_security_group_association" "proxy" {
  subnet_id                 = azurerm_subnet.proxy.id
  network_security_group_id = azurerm_network_security_group.proxy.id
}

resource "azurerm_lb" "api" {
  name                = "${var.name}-api"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "Standard"
  frontend_ip_configuration {
    name                 = "https"
    public_ip_address_id = azurerm_public_ip.gateway.id
  }
}

resource "azurerm_lb_backend_address_pool" "api" {
  name            = "api"
  loadbalancer_id = azurerm_lb.api.id
}

resource "azurerm_network_interface_backend_address_pool_association" "api" {
  for_each                = local.api_nodes
  network_interface_id    = azurerm_network_interface.api[each.key].id
  ip_configuration_name   = "primary"
  backend_address_pool_id = azurerm_lb_backend_address_pool.api.id
}

resource "azurerm_lb_probe" "api" {
  name            = "health"
  loadbalancer_id = azurerm_lb.api.id
  protocol        = "Http"
  port            = 8080
  request_path    = "/healthz"
}

resource "azurerm_lb_rule" "https" {
  name                           = "https"
  loadbalancer_id                = azurerm_lb.api.id
  protocol                       = "Tcp"
  frontend_port                  = 443
  backend_port                   = 443
  frontend_ip_configuration_name = "https"
  backend_address_pool_ids       = [azurerm_lb_backend_address_pool.api.id]
  probe_id                       = azurerm_lb_probe.api.id
  disable_outbound_snat          = true
}
