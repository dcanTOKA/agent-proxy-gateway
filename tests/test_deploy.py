import subprocess

from scripts.deploy import render_network, render_squid


def test_each_listener_maps_to_its_private_address():
    config = render_squid(["10.40.2.10", "10.40.2.11"], "10.40.1.0/24", ["example.com"])
    assert "http_port 10.40.2.10:3129" in config
    assert "tcp_outgoing_address 10.40.2.11 exit_1" in config
    assert config.index("http_access deny forbidden") < config.index("http_access allow clients")
    assert "acl allowed_domains dstdomain example.com\n" in config


def test_secondary_address_setup_is_valid_shell(tmp_path):
    script = tmp_path / "network.sh"
    script.write_text(render_network(["10.40.2.10", "10.40.2.11"]))
    subprocess.run(["sh", "-n", str(script)], check=True)
    assert "ip address add 10.40.2.11/24" in script.read_text()
