from __future__ import annotations

import argparse
import asyncio
import sys

from pydantic import SecretStr

from app.core.config import get_settings
from app.core.secrets import RuntimeSecretStore
from app.database import Database
from app.models import ProviderType, SshAuthMethod
from app.registry import RegistryOnboardingService


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="ASO non-destructive registry onboarding CLI")
    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("list")
    sub.add_parser("readiness")

    secret = sub.add_parser("secret-write")
    secret.add_argument("--scope", required=True)
    secret.add_argument("--name", required=True)

    provider = sub.add_parser("add-provider")
    provider.add_argument("--key", required=True)
    provider.add_argument("--display-name", required=True)
    provider.add_argument("--type", choices=[item.value for item in ProviderType], required=True)
    provider.add_argument("--credential-ref", required=True)
    provider.add_argument("--region", required=True)
    provider.add_argument("--server-type", required=True)
    provider.add_argument("--image", required=True)

    node = sub.add_parser("add-node")
    node.add_argument("--name", required=True)
    node.add_argument("--provider-key", required=True)
    node.add_argument("--master-node-id", required=True)
    node.add_argument("--host", required=True)
    node.add_argument("--port", type=int, required=True)
    node.add_argument("--provider-server-id", required=True)
    node.add_argument("--region")
    node.add_argument("--server-type")
    node.add_argument("--ssh-username", default="root")
    node.add_argument("--ssh-port", type=int, default=22)
    node.add_argument("--ssh-auth-method", choices=[item.value for item in SshAuthMethod], required=True)
    node.add_argument("--ssh-secret-ref", required=True)
    node.add_argument("--ssh-public-key")
    node.add_argument("--panel-base-path")
    node.add_argument("--api-token-ref")
    return root


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.command == "secret-write":
        value = sys.stdin.read()
        if not value.strip():
            raise ValueError("secret input is empty")
        ref = RuntimeSecretStore(settings.runtime_secret_dir).write(
            args.scope,
            args.name,
            SecretStr(value.rstrip("\n")),
        )
        print(ref)
        return 0

    database = Database.from_settings(settings)
    service = RegistryOnboardingService(database)
    try:
        if args.command == "list":
            providers = await service.list_providers()
            nodes = await service.list_nodes()
            print("Providers:")
            if not providers:
                print("  (none)")
            for item in providers:
                print(
                    f"  - {item.key}: {item.provider_type.value} "
                    f"region={item.default_region or '-'} type={item.default_server_type or '-'}"
                )
            print("Nodes:")
            if not nodes:
                print("  (none)")
            for item in nodes:
                print(
                    f"  - {item.name}: {item.current_host}:{item.current_port} "
                    f"master={item.master_node_id} state={item.state.value}"
                )
            return 0

        if args.command == "readiness":
            value = await service.readiness()
            print(f"providers={value.provider_count}")
            print(f"nodes={value.node_count}")
            print(f"current_vps={value.current_vps_count}")
            print(f"node_credentials={value.credential_count}")
            print(f"ready={'yes' if value.ready else 'no'}")
            return 0 if value.ready else 3

        if args.command == "add-provider":
            provider = await service.register_provider(
                key=args.key,
                display_name=args.display_name,
                provider_type=ProviderType(args.type),
                credential_ref=args.credential_ref,
                default_region=args.region,
                default_server_type=args.server_type,
                default_image=args.image,
            )
            print(f"Provider ready: {provider.key} ({provider.provider_type.value})")
            return 0

        if args.command == "add-node":
            node = await service.register_node(
                name=args.name,
                provider_key=args.provider_key,
                master_node_id=args.master_node_id,
                current_host=args.host,
                current_port=args.port,
                provider_server_id=args.provider_server_id,
                region=args.region,
                server_type=args.server_type,
                ssh_username=args.ssh_username,
                ssh_port=args.ssh_port,
                ssh_auth_method=SshAuthMethod(args.ssh_auth_method),
                ssh_secret_ref=args.ssh_secret_ref,
                ssh_public_key=args.ssh_public_key,
                panel_base_path=args.panel_base_path,
                api_token_ref=args.api_token_ref,
            )
            print(f"Node ready: {node.name} ({node.id})")
            return 0
    finally:
        await database.dispose()
    raise RuntimeError("unsupported command")


def main() -> None:
    args = parser().parse_args()
    try:
        raise SystemExit(asyncio.run(run(args)))
    except Exception as exc:
        print(f"Registry setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
