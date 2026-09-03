#!/usr/bin/env python3
# push_to_d1.py
"""
CLI Script to push extracted directory batches into Cloudflare D1.
Supports --full-reset with interactive safety confirmation.
"""

import sys
import os
import json
import argparse
import toml
from cloudflare_db import CloudflareD1
from agent_engine import DisambiguationAgent, QualityAuditAgent


def load_secrets():
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        return toml.load(secrets_path)
    return {}


def main():
    parser = argparse.ArgumentParser(description="Push extracted JSON/CSV records to Cloudflare D1")
    parser.add_argument("--file", "-f", required=True, help="Path to JSON or CSV file to push")
    parser.add_argument("--full-reset", action="store_true", help="Reset D1 database schema before pushing")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt for full reset")
    args = parser.parse_args()

    secrets = load_secrets()
    cf_account = secrets.get("CLOUDFLARE_ACCOUNT_ID") or os.getenv("CLOUDFLARE_ACCOUNT_ID")
    cf_db_id = secrets.get("CLOUDFLARE_DATABASE_ID") or os.getenv("CLOUDFLARE_DATABASE_ID")
    cf_token = secrets.get("CLOUDFLARE_API_TOKEN") or os.getenv("CLOUDFLARE_API_TOKEN")

    if not cf_account or not cf_db_id or not cf_token:
        print("❌ Error: Missing Cloudflare credentials in secrets.toml or environment variables!")
        sys.exit(1)

    db = CloudflareD1(cf_account, cf_db_id, cf_token)

    if args.full_reset:
        if not args.yes:
            confirm = input("⚠️ WARNING: --full-reset will WIPE ALL DATA in Cloudflare D1! Are you sure? [y/N]: ")
            if confirm.lower() != 'y':
                print("Operation canceled.")
                sys.exit(0)

        print("🔄 Executing reset_schema.sql on Cloudflare D1...")
        sql_path = "reset_schema.sql"
        if os.path.exists(sql_path):
            with open(sql_path, "r", encoding="utf-8") as f:
                sql_statements = f.read().split(";")
                for stmt in sql_statements:
                    stmt_clean = stmt.strip()
                    if stmt_clean:
                        db.query(stmt_clean)
            print("✅ Database schema successfully reset!")
        else:
            print(f"❌ Error: {sql_path} not found!")
            sys.exit(1)

    print(f"📦 Loading records from {args.file}...")
    with open(args.file, "r", encoding="utf-8") as f:
        records = json.load(f)

    cleaned_batch = []
    for r in records:
        proc = DisambiguationAgent.process_entity(r)
        audited = QualityAuditAgent.audit(proc)
        cleaned_batch.append(audited)

    print(f"🚀 Pushing {len(cleaned_batch)} records to Database...")
    committed = db.bulk_insert_companies(cleaned_batch, fuzzy_check=True)
    print(f"🎉 Done! Committed {committed} records to Database.")


if __name__ == "__main__":
    main()