locals {
  api_subnet   = "10.40.1.0/24"
  proxy_subnet = "10.40.2.0/24"
  api_nodes    = { for i in range(var.api_vm_count) : tostring(i) => i }
  proxy_nodes = { for i in range(var.proxy_vm_count) : tostring(i) => {
    index = i
    ips   = [for j in range(var.proxy_ips_per_vm) : cidrhost(local.proxy_subnet, 10 + i * 8 + j)]
  } }
  proxy_addresses = merge([for key, node in local.proxy_nodes : {
    for j, ip in node.ips : "${key}-${j}" => { node = key, index = j, ip = ip }
  }]...)
  cloud_init = file("${path.module}/cloud-init.yaml")
}

resource "azurerm_resource_group" "main" {
  name     = var.name
  location = var.location
}

resource "azurerm_virtual_network" "main" {
  name                = "${var.name}-vnet"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = ["10.40.0.0/16"]
}

resource "azurerm_subnet" "api" {
  name                 = "api"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.api_subnet]
}

resource "azurerm_subnet" "proxy" {
  name                 = "proxy"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.proxy_subnet]
}

resource "azurerm_public_ip" "gateway" {
  name                = "${var.name}-gateway"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_public_ip" "api" {
  for_each            = local.api_nodes
  name                = "${var.name}-api-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_public_ip" "proxy" {
  for_each            = local.proxy_addresses
  name                = "${var.name}-proxy-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_interface" "api" {
  for_each            = local.api_nodes
  name                = "${var.name}-api-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  ip_configuration {
    name                          = "primary"
    primary                       = true
    subnet_id                     = azurerm_subnet.api.id
    private_ip_address_allocation = "Static"
    private_ip_address            = cidrhost(local.api_subnet, 10 + each.value)
    public_ip_address_id          = azurerm_public_ip.api[each.key].id
  }
}

resource "azurerm_network_interface" "proxy" {
  for_each            = local.proxy_nodes
  name                = "${var.name}-proxy-${each.key}"
  location            = var.location
  resource_group_name = azurerm_resource_group.main.name
  dynamic "ip_configuration" {
    for_each = { for j, ip in each.value.ips : tostring(j) => ip }
    content {
      name                          = "ip-${ip_configuration.key}"
      primary                       = ip_configuration.key == "0"
      subnet_id                     = azurerm_subnet.proxy.id
      private_ip_address_allocation = "Static"
      private_ip_address            = ip_configuration.value
      public_ip_address_id          = azurerm_public_ip.proxy["${each.key}-${ip_configuration.key}"].id
    }
  }
}

resource "azurerm_linux_virtual_machine" "api" {
  for_each                        = local.api_nodes
  name                            = "${var.name}-api-${each.key}"
  location                        = var.location
  resource_group_name             = azurerm_resource_group.main.name
  size                            = var.api_vm_size
  admin_username                  = var.admin_user
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.api[each.key].id]
  custom_data                     = base64encode(local.cloud_init)
  admin_ssh_key {
    username   = var.admin_user
    public_key = var.ssh_public_key
  }
  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }
  depends_on = [azurerm_subnet_network_security_group_association.api]
}

resource "azurerm_linux_virtual_machine" "proxy" {
  for_each                        = local.proxy_nodes
  name                            = "${var.name}-proxy-${each.key}"
  location                        = var.location
  resource_group_name             = azurerm_resource_group.main.name
  size                            = var.proxy_vm_size
  admin_username                  = var.admin_user
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.proxy[each.key].id]
  custom_data                     = base64encode(local.cloud_init)
  admin_ssh_key {
    username   = var.admin_user
    public_key = var.ssh_public_key
  }
  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
  }
  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }
  depends_on = [azurerm_subnet_network_security_group_association.proxy]
}
