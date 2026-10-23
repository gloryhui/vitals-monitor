#!/usr/bin/env python3
"""Manage dashboard accounts in the monitor's SQLite database.

    sudo python3 -m vitals.cli list
    sudo python3 -m vitals.cli add alice
    sudo python3 -m vitals.cli passwd alice
    sudo python3 -m vitals.cli delete alice

The service picks changes up immediately; no restart is needed.
"""
import argparse
import getpass
import os
import sys
from datetime import datetime
from pathlib import Path

from .auth import MIN_PASSWORD_LENGTH, AuthError, AuthStore

DEFAULT_DB = Path(os.environ.get("VITALS_DB") or os.environ.get("SERVER_INFO_DB", "/var/lib/server-info/metrics.sqlite3"))


def prompt_password():
    first = getpass.getpass("新密码: ")
    if len(first) < MIN_PASSWORD_LENGTH:
        sys.exit(f"密码至少需要 {MIN_PASSWORD_LENGTH} 个字符")
    if first != getpass.getpass("再输入一次: "):
        sys.exit("两次输入的密码不一致")
    return first


def stamp(value):
    return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")


def main(argv=None):
    parser = argparse.ArgumentParser(description="管理服务器状态页的登录账号")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite 路径（默认 {DEFAULT_DB}）")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="创建账号")
    add.add_argument("username")
    add.add_argument("--password", help="非交互式提供密码（会留在 shell 历史里，不推荐）")

    change = commands.add_parser("passwd", help="修改密码")
    change.add_argument("username")
    change.add_argument("--password")

    remove = commands.add_parser("delete", help="删除账号")
    remove.add_argument("username")

    commands.add_parser("list", help="列出账号")

    args = parser.parse_args(argv)
    try:
        store = AuthStore(args.db)
    except Exception as exc:  # noqa: BLE001 - surface any storage problem to the operator
        sys.exit(f"无法打开数据库 {args.db}: {exc}")
    try:
        if args.command == "list":
            users = store.list_users()
            if not users:
                print("还没有账号。")
            for user in users:
                print(f"{user['username']}\t创建 {stamp(user['created_at'])}\t最近修改 {stamp(user['updated_at'])}")
            return 0
        if args.command == "add":
            if store.has_user(args.username):
                sys.exit(f"账号 {args.username} 已存在；用 passwd 修改密码")
            store.add_user(args.username, args.password or prompt_password())
            print(f"已创建账号 {args.username}")
            return 0
        if args.command == "passwd":
            if not store.has_user(args.username):
                sys.exit(f"账号 {args.username} 不存在")
            store.add_user(args.username, args.password or prompt_password(), replace=True)
            print(f"已更新账号 {args.username} 的密码")
            return 0
        if args.command == "delete":
            if not store.delete_user(args.username):
                sys.exit(f"账号 {args.username} 不存在")
            print(f"已删除账号 {args.username}，其登录会话同时失效")
            return 0
        return 1
    except AuthError as exc:
        sys.exit(str(exc))
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
