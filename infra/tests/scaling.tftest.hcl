mock_provider "azurerm" {}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  ssh_public_key  = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBbCX+DbqDDzm7h6rsu7WhCiEJc8lCw8KltASuPBhW8K"
  admin_cidrs     = ["203.0.113.10/32"]
  client_cidrs    = ["203.0.113.20/32"]
}

run "two_machine_start" {
  command = plan
  assert {
    condition     = length(azurerm_linux_virtual_machine.api) == 1 && length(azurerm_linux_virtual_machine.proxy) == 1
    error_message = "Default deployment must have one API and one proxy VM."
  }
  assert {
    condition     = length(azurerm_public_ip.proxy) == 1
    error_message = "Default proxy must have one public IP."
  }
}

run "independent_scaling" {
  command = plan
  variables {
    api_vm_count     = 2
    proxy_vm_count   = 3
    proxy_ips_per_vm = 2
  }
  assert {
    condition     = length(azurerm_linux_virtual_machine.api) == 2 && length(azurerm_linux_virtual_machine.proxy) == 3
    error_message = "API and proxy groups must scale independently."
  }
  assert {
    condition     = length(azurerm_public_ip.proxy) == 6
    error_message = "Three proxies with two addresses each must have six public IPs."
  }
  assert {
    condition     = length(distinct(flatten([for node in local.proxy_nodes : node.ips]))) == 6
    error_message = "Private exit addresses must not overlap."
  }
}
