import argparse
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o600)


def render_squid(private_ips: list[str], api_subnet: str, domains: list[str]) -> str:
    base = (ROOT / "deploy/squid.local.conf").read_text().splitlines()
    rules = [
        line
        for line in base
        if not line.startswith(("http_port", "acl clients", "acl allowed_domains"))
    ]
    listeners = []
    for index, address in enumerate(private_ips):
        port = 3128 + index
        listeners.extend(
            [
                f"http_port {private_ips[0]}:{port}",
                f"acl exit_{index} localport {port}",
                f"tcp_outgoing_address {address} exit_{index}",
            ]
        )
    return "\n".join(
        [
            *listeners,
            f"acl clients src {api_subnet}",
            "acl allowed_domains dstdomain " + " ".join(domains),
            *rules,
            "",
        ]
    )


def render_network(private_ips: list[str]) -> str:
    lines = [
        "#!/bin/sh",
        "set -eu",
        "device=$(ip -4 route show default | awk '{print $5; exit}')",
    ]
    for address in private_ips[1:]:
        lines.append(
            f'ip -4 address show dev "$device" | grep -Fq " {address}/24 " '
            f'|| ip address add {address}/24 dev "$device"'
        )
    return "\n".join(lines) + "\n"


def make_archive(directory: Path) -> Path:
    archive = directory.with_suffix(".tar.gz")

    def exclude_cache(info):
        return None if "__pycache__" in info.name or info.name.endswith(".pyc") else info

    with tarfile.open(archive, "w:gz") as bundle:
        for path in directory.iterdir():
            bundle.add(path, arcname=path.name, filter=exclude_cache)
    archive.chmod(0o600)
    return archive


def upload(node: dict, archive: Path, admin_user: str, identity: str | None, proxy: bool):
    target = f"{admin_user}@{node['host']}"
    options = ["-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15"]
    if identity:
        options += ["-i", identity]
    remote_archive = f"/tmp/agent-gateway-{node['name']}.tar.gz"
    subprocess.run(["scp", *options, str(archive), f"{target}:{remote_archive}"], check=True)
    commands = [
        "set -eu",
        "sudo cloud-init status --wait",
        "sudo install -d -m 700 /opt/agent-gateway",
        f"sudo tar -xzf {remote_archive} -C /opt/agent-gateway",
        f"rm -f {remote_archive}",
        "cd /opt/agent-gateway",
    ]
    if proxy:
        commands += [
            "sudo chmod 700 setup-network.sh",
            "sudo cp gateway-addresses.service /etc/systemd/system/",
            "sudo systemctl daemon-reload",
            "sudo systemctl enable gateway-addresses.service",
            "sudo systemctl restart gateway-addresses.service",
        ]
    commands += [
        "sudo docker compose build",
        "sudo docker compose run --rm --no-deps squid squid -k parse"
        if proxy
        else "sudo docker compose config --quiet",
        "sudo docker compose up -d --remove-orphans --force-recreate",
    ]
    subprocess.run(["ssh", *options, target, "\n".join(commands)], check=True)


def main():
    parser = argparse.ArgumentParser(
        description="Render deployment bundles; optionally deploy over SSH"
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--tls-cert", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--allowed-domain", action="append", required=True)
    parser.add_argument("--identity")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("GATEWAY_API_TOKEN", "")
    search_key = os.environ.get("GATEWAY_SEARCH_API_KEY", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", token):
        parser.error("Set GATEWAY_API_TOKEN to a URL-safe random token of at least 32 characters")
    if search_key and not re.fullmatch(r"[A-Za-z0-9_-]+", search_key):
        parser.error("Search API key must contain only letters, digits, underscores and hyphens")
    domains = [value.lower().rstrip(".") for value in args.allowed_domain]
    if not all(re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", domain) for domain in domains):
        parser.error("Use explicit ASCII domain names; no schemes, ports or wildcards")
    if search_key and "api.search.brave.com" not in domains:
        parser.error("Add --allowed-domain api.search.brave.com for web search")
    inventory = json.loads(args.inventory.read_text())
    admin_user = inventory["admin_user"]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", admin_user):
        parser.error("Invalid SSH username")
    ipaddress.IPv4Network(inventory["api_subnet"])
    for node in inventory["apis"] + inventory["proxies"]:
        if not re.fullmatch(r"(?:api|proxy)-\d+", node["name"]):
            parser.error("Invalid node name")
        ipaddress.IPv4Address(node["host"])
    for node in inventory["proxies"]:
        if not 1 <= len(node["private_ips"]) <= 4:
            parser.error("Each proxy requires 1 to 4 private IPs")
        for address in node["private_ips"]:
            ipaddress.IPv4Address(address)

    proxies = [
        {
            "name": f"{node['name']}-ip-{index}",
            "url": f"http://{node['private_ips'][0]}:{3128 + index}",
        }
        for node in inventory["proxies"]
        for index, address in enumerate(node["private_ips"])
    ]
    if not proxies or not inventory["apis"]:
        parser.error("Inventory must include API and proxy nodes")
    output = ROOT / "work/deploy"
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for node in inventory["proxies"]:
        directory = output / node["name"]
        directory.mkdir(exist_ok=True, mode=0o700)
        shutil.copytree(ROOT / "deploy/squid", directory / "squid", dirs_exist_ok=True)
        shutil.copyfile(ROOT / "deploy/proxy.compose.yaml", directory / "compose.yaml")
        write(
            directory / "squid.conf",
            render_squid(node["private_ips"], inventory["api_subnet"], domains),
        )
        write(directory / "setup-network.sh", render_network(node["private_ips"]))
        write(
            directory / "gateway-addresses.service",
            """[Unit]
Description=Additional Azure proxy addresses
Wants=network-online.target
After=network-online.target
Before=docker.service

[Service]
Type=oneshot
ExecStart=/opt/agent-gateway/setup-network.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
""",
        )
        archive = make_archive(directory)
        print(f"Prepared {node['name']}")
        if args.apply:
            upload(node, archive, admin_user, args.identity, proxy=True)

    for node in inventory["apis"]:
        directory = output / node["name"]
        directory.mkdir(exist_ok=True, mode=0o700)
        shutil.copytree(ROOT / "app", directory / "app", dirs_exist_ok=True)
        for name in ("Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock"):
            shutil.copyfile(ROOT / name, directory / name)
        shutil.copyfile(ROOT / "deploy/api.compose.yaml", directory / "compose.yaml")
        shutil.copyfile(ROOT / "deploy/nginx.conf", directory / "nginx.conf")
        write(directory / "tls/cert.pem", args.tls_cert.read_text())
        write(directory / "tls/key.pem", args.tls_key.read_text())
        write(
            directory / ".env",
            "\n".join(
                [
                    f"GATEWAY_API_TOKEN={token}",
                    f"GATEWAY_PROXIES={json.dumps(proxies)}",
                    f"GATEWAY_ALLOWED_DOMAINS={json.dumps(domains)}",
                    f"GATEWAY_SEARCH_API_KEY={search_key}",
                    "GATEWAY_REQUESTS_PER_MINUTE=60",
                    "",
                ]
            ),
        )
        archive = make_archive(directory)
        print(f"Prepared {node['name']}")
        if args.apply:
            upload(node, archive, admin_user, args.identity, proxy=False)


if __name__ == "__main__":
    main()
