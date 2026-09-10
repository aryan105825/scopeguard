"""
common/client_admin.py
------------------------
Admin CLI for onboarding/removing ScopeGuard clients.
"""

import argparse
import json
import sys

from common import client_config


def _cmd_add(args: argparse.Namespace) -> int:
    sow_source = None
    if args.sow_type or args.sow_ref:
        if not (args.sow_type and args.sow_ref):
            print("Both --sow-type and --sow-ref are required together.", file=sys.stderr)
            return 2
        
        # Route to the correct JSON key based on source type
        if args.sow_type == "notion":
            ref_field = "page_id"
        elif args.sow_type == "drive":
            ref_field = "file_id"
        else:
            ref_field = "file_path"
            
        sow_source = {"type": args.sow_type, ref_field: args.sow_ref}

    client_config.upsert_client(
        client_id=args.client_id,
        sow_source=sow_source,
        slack_channel_id=args.channel,
    )
    print(f"Onboarded client_id={args.client_id!r}.")
    print(f"Config file: {client_config.config_path()}")
    return 0


def _cmd_remove(args: argparse.Namespace) -> int:
    existed = client_config.remove_client(args.client_id)
    if existed:
        print(f"Removed client_id={args.client_id!r}.")
        return 0
    print(f"No such client_id={args.client_id!r}.", file=sys.stderr)
    return 1


def _cmd_list(_args: argparse.Namespace) -> int:
    client_ids = client_config.list_client_ids()
    if not client_ids:
        print("No clients onboarded yet.")
        print(f"Config file: {client_config.config_path()}")
        return 0
    channel_map = {v: k for k, v in client_config.get_channel_map().items()}
    for client_id in client_ids:
        sow_source = client_config.get_sow_source(client_id)
        channel_id = channel_map.get(client_id, "(no Slack channel configured)")
        print(f"{client_id}\n  sow_source: {json.dumps(sow_source)}\n  slack_channel_id: {channel_id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m common.client_admin",
        description="Onboard/remove ScopeGuard clients without editing source.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Onboard or update a client")
    add_parser.add_argument("--client-id", required=True)
    add_parser.add_argument("--sow-type", choices=["notion", "drive", "file"])
    add_parser.add_argument(
        "--sow-ref", help="Notion page_id, Drive file_id, or local file_path if --sow-type file"
    )
    add_parser.add_argument("--channel", help="Slack channel_id this client's messages arrive in")
    add_parser.set_defaults(func=_cmd_add)

    remove_parser = subparsers.add_parser("remove", help="Remove a client")
    remove_parser.add_argument("--client-id", required=True)
    remove_parser.set_defaults(func=_cmd_remove)

    list_parser = subparsers.add_parser("list", help="List onboarded clients")
    list_parser.set_defaults(func=_cmd_list)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())