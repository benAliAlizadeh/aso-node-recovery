from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pydantic import SecretStr

from app.core.config import get_settings
from app.core.secrets import RuntimeSecretStore
from app.database import Database
from app.models import ProviderType, SecretReferenceBackend, SshAuthMethod
from app.registry import RegistryOnboardingService, SmartRegistryOnboardingService
from app.registry.management import RegistryManagementService


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="ASO non-destructive registry onboarding CLI")
    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("list")
    sub.add_parser("readiness")

    host_key = sub.add_parser("ssh-host-key-preview")
    host_key.add_argument("--host", required=True)
    host_key.add_argument("--port", type=int, default=22)

    trust_key = sub.add_parser("ssh-host-key-trust")
    trust_key.add_argument("--host", required=True)
    trust_key.add_argument("--port", type=int, default=22)
    trust_key.add_argument("--fingerprint", required=True)

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

    smart_provider = sub.add_parser("smart-add-provider")
    smart_provider.add_argument("--key", required=True)
    smart_provider.add_argument("--display-name", required=True)
    smart_provider.add_argument(
        "--type", choices=[item.value for item in ProviderType], required=True
    )
    smart_provider.add_argument("--credential-ref", required=True)
    smart_provider.add_argument(
        "--credential-backend",
        choices=[SecretReferenceBackend.FILE.value, SecretReferenceBackend.ENVIRONMENT.value],
        default=SecretReferenceBackend.FILE.value,
    )

    node = sub.add_parser("add-node")
    node.add_argument("--name", required=True)
    node.add_argument("--provider-key", required=True)
    node.add_argument("--master-node-id", required=True)
    node.add_argument("--host", required=True)
    node.add_argument("--port", type=int, required=True)
    node.add_argument("--provider-server-id", required=True)
    node.add_argument("--provider-host")
    node.add_argument("--region")
    node.add_argument("--server-type")
    node.add_argument("--provider-image")
    node.add_argument("--ssh-username", default="root")
    node.add_argument("--ssh-port", type=int, default=22)
    node.add_argument("--ssh-auth-method", choices=[item.value for item in SshAuthMethod], required=True)
    node.add_argument("--ssh-secret-ref", required=True)
    node.add_argument("--ssh-public-key")
    node.add_argument("--panel-base-path")
    node.add_argument("--api-token-ref")

    for command in ("smart-preview-node", "smart-add-node"):
        smart_node = sub.add_parser(command)
        smart_node.add_argument("--provider-key", required=True)
        smart_node.add_argument("--provider-server-id", required=True)
        smart_node.add_argument("--master-node-id", type=int, required=True)
        smart_node.add_argument("--api-token-ref")
        smart_node.add_argument("--region-override")
        smart_node.add_argument("--server-type-override")
        smart_node.add_argument("--image-override")
        if command == "smart-add-node":
            smart_node.add_argument("--name")
            smart_node.add_argument("--ssh-username", default="root")
            smart_node.add_argument("--ssh-port", type=int, default=22)
            smart_node.add_argument(
                "--ssh-auth-method", choices=[item.value for item in SshAuthMethod], required=True
            )
            smart_node.add_argument("--ssh-secret-ref", required=True)
            smart_node.add_argument("--ssh-public-key")
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
    smart = SmartRegistryOnboardingService(database, settings)
    management = RegistryManagementService(database, settings)
    try:
        if args.command == "ssh-host-key-preview":
            candidate = await management.inspect_ssh_host_key(host=args.host, port=args.port)
            print(f"host={candidate.host}")
            print(f"port={candidate.port}")
            print(f"algorithm={candidate.algorithm}")
            print(f"fingerprint={candidate.fingerprint}")
            return 0

        if args.command == "ssh-host-key-trust":
            candidate = await management.trust_ssh_host_key(
                host=args.host,
                port=args.port,
                expected_fingerprint=args.fingerprint,
            )
            print(f"Trusted SSH host key: {candidate.host}:{candidate.port}")
            print(f"algorithm={candidate.algorithm}")
            print(f"fingerprint={candidate.fingerprint}")
            return 0

        if args.command == "list":
            providers = await service.list_providers()
            nodes = await service.list_nodes()
            print("Providers:")
            if not providers:
                print("  (none)")
            for item in providers:
                print(
                    f"  - {item.key}: {item.provider_type.value} "
                    f"region={item.default_region or '-'} type={item.default_server_type or '-'} "
                    f"image={item.default_image or '-'}"
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

        if args.command == "smart-add-provider":
            provider = await smart.validate_and_register_provider(
                key=args.key,
                display_name=args.display_name,
                provider_type=ProviderType(args.type),
                credential_ref=args.credential_ref,
                credential_backend=SecretReferenceBackend(args.credential_backend),
            )
            print(
                f"Provider API verified and registered: {provider.key} "
                f"({provider.provider_type.value})"
            )
            return 0

        if args.command == "add-node":
            node = await service.register_node(
                name=args.name,
                provider_key=args.provider_key,
                master_node_id=args.master_node_id,
                current_host=args.host,
                current_port=args.port,
                provider_server_id=args.provider_server_id,
                provider_host=args.provider_host,
                region=args.region,
                server_type=args.server_type,
                provider_image=args.provider_image,
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

        if args.command == "smart-preview-node":
            discovered = await smart.discover_node(
                provider_key=args.provider_key,
                provider_server_id=args.provider_server_id,
                master_node_id=args.master_node_id,
                api_token_ref=args.api_token_ref,
                region_override=args.region_override,
                server_type_override=args.server_type_override,
                image_override=args.image_override,
            )
            print(json.dumps(discovered.safe_summary(), indent=2, sort_keys=True))
            return 0

        if args.command == "smart-add-node":
            node, discovered = await smart.validate_and_register_node(
                name=args.name,
                provider_key=args.provider_key,
                provider_server_id=args.provider_server_id,
                master_node_id=args.master_node_id,
                ssh_username=args.ssh_username,
                ssh_port=args.ssh_port,
                ssh_auth_method=SshAuthMethod(args.ssh_auth_method),
                ssh_secret_ref=args.ssh_secret_ref,
                ssh_public_key=args.ssh_public_key,
                api_token_ref=args.api_token_ref,
                region_override=args.region_override,
                server_type_override=args.server_type_override,
                image_override=args.image_override,
            )
            print(json.dumps(discovered.safe_summary(), indent=2, sort_keys=True))
            print(f"Node verified and registered: {node.name} ({node.id})")
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
