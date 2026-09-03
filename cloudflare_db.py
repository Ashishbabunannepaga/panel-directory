# cloudflare_db.py
"""
Production REST API Client for Cloudflare D1 with Local SQLite Mirror Fallback.
Features: Authentication, User Management, Advanced Multi-Faceted Filtering,
Fuzzy Deduplication, and Idempotent Upserts.
"""

import requests
import json
import uuid
import re
import time
import sqlite3
import hashlib
import os
from typing import List, Dict, Any, Optional

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

LOCAL_DB_PATH = "local_d1_mirror.db"


def hash_password(password: str) -> str:
    """Secure SHA-256 password hashing with salt."""
    salt = "MSME_PORTAL_SECURE_SALT_2026"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()


class CloudflareD1:
    """High-performance D1 client with in-memory bulk caching and Local SQLite fallback."""

    def __init__(self, account_id: str, database_id: str, api_token: str):
        self.url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{database_id}/query"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        self.d1_quota_exceeded = False
        self._init_local_sqlite()
        self._ensure_default_admin()

    def _init_local_sqlite(self):
        """Initializes local SQLite mirror database."""
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY,
            panel_no INTEGER,
            raw_name TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            aliases TEXT DEFAULT '[]',
            address TEXT DEFAULT '',
            pincode TEXT DEFAULT '',
            website TEXT DEFAULT '',
            emails TEXT DEFAULT '[]',
            phones TEXT DEFAULT '[]',
            representatives TEXT DEFAULT '[]',
            nature_of_business TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS possible_duplicates (
            id TEXT PRIMARY KEY,
            incoming_name TEXT NOT NULL,
            existing_name TEXT NOT NULL,
            similarity_score REAL NOT NULL,
            pincode TEXT DEFAULT '',
            incoming_data TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        conn.close()

    def _ensure_default_admin(self):
        """Seeds default admin if no users exist."""
        admin_user = self.get_user_by_username("admin")
        if not admin_user:
            self.create_user("admin", "admin123", role="admin", full_name="Master Administrator")

    def _query_local(self, sql: str, params: list = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            cur.execute(sql, params or [])
            if sql.strip().upper().startswith("SELECT"):
                rows = [dict(r) for r in cur.fetchall()]
                conn.close()
                return rows
            else:
                conn.commit()
                conn.close()
                return []
        except Exception:
            conn.close()
            return []

    def query(self, sql: str, params: list = None, retries: int = 1) -> List[Dict[str, Any]]:
        """Executes query on Cloudflare D1 with automatic Local SQLite fallback."""
        if self.d1_quota_exceeded:
            return self._query_local(sql, params)

        payload = {"sql": sql, "params": params or []}

        for attempt in range(retries):
            try:
                res = requests.post(self.url, headers=self.headers, json=payload, timeout=20)
                res_data = res.json()

                if res.status_code == 200 and res_data.get("success"):
                    results = res_data.get("result", [])
                    return results[0].get("results", []) if results else []
                else:
                    errors = res_data.get("errors", [])
                    if any(e.get("code") == 7500 for e in errors):
                        self.d1_quota_exceeded = True
                        return self._query_local(sql, params)
            except Exception:
                return self._query_local(sql, params)

        return self._query_local(sql, params)

    # =========================================================================
    # USER & AUTHENTICATION METHODS
    # =========================================================================

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        pwd_hash = hash_password(password)
        sql = "SELECT id, username, role, full_name FROM users WHERE username = ? AND password_hash = ?"
        results = self._query_local(sql, [username.strip().lower(), pwd_hash])
        return results[0] if results else None

    def create_user(self, username: str, password: str, role: str = "user", full_name: str = "") -> bool:
        user_id = str(uuid.uuid4())
        pwd_hash = hash_password(password)
        sql = "INSERT INTO users (id, username, password_hash, role, full_name) VALUES (?, ?, ?, ?, ?)"
        params = [user_id, username.strip().lower(), pwd_hash, role, full_name.strip()]
        try:
            self._query_local(sql, params)
            self.query(sql, params)
            return True
        except Exception:
            return False

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT id, username, role, full_name FROM users WHERE username = ?"
        res = self._query_local(sql, [username.strip().lower()])
        return res[0] if res else None

    def get_all_users(self) -> List[Dict[str, Any]]:
        sql = "SELECT id, username, role, full_name, created_at FROM users ORDER BY created_at DESC"
        return self._query_local(sql)

    def delete_user(self, user_id: str) -> bool:
        sql = "DELETE FROM users WHERE id = ?"
        self._query_local(sql, [user_id])
        self.query(sql, [user_id])
        return True

    # =========================================================================
    # ADVANCED MULTI-FACETED FILTERING & SEARCH
    # =========================================================================

    def get_portal_kpis(self) -> Dict[str, Any]:
        """Calculates dashboard summary metrics."""
        companies = self._query_local("SELECT pincode, emails, phones, nature_of_business FROM companies")
        total_companies = len(companies)

        emails_count = sum(1 for c in companies if c.get("emails") and c.get("emails") != "[]")
        phones_count = sum(1 for c in companies if c.get("phones") and c.get("phones") != "[]")
        pincodes_count = len(set(c.get("pincode") for c in companies if c.get("pincode")))

        return {
            "total_companies": total_companies,
            "emails_count": emails_count,
            "phones_count": phones_count,
            "unique_pincodes": pincodes_count
        }

    def filter_companies_advanced(
        self,
        search_query: str = "",
        sector_keyword: str = "All",
        location_keyword: str = "",
        pincode_keyword: str = "",
        entity_type: str = "All",
        has_email: bool = False,
        has_phone: bool = False,
        has_website: bool = False,
        limit: int = 150
    ) -> List[Dict[str, Any]]:
        """Multi-criteria search filter engine."""
        conditions = ["1=1"]
        params = []

        if search_query and search_query.strip():
            pat = f"%{search_query.strip().lower()}%"
            conditions.append("""(
                LOWER(canonical_name) LIKE ? OR 
                LOWER(normalized_name) LIKE ? OR 
                LOWER(aliases) LIKE ? OR 
                LOWER(representatives) LIKE ? OR 
                LOWER(nature_of_business) LIKE ?
            )""")
            params.extend([pat, pat, pat, pat, pat])

        if sector_keyword and sector_keyword != "All":
            conditions.append("LOWER(nature_of_business) LIKE ?")
            params.append(f"%{sector_keyword.lower()}%")

        if location_keyword and location_keyword.strip():
            conditions.append("LOWER(address) LIKE ?")
            params.append(f"%{location_keyword.strip().lower()}%")

        if pincode_keyword and pincode_keyword.strip():
            conditions.append("pincode LIKE ?")
            params.append(f"%{pincode_keyword.strip()}%")

        if entity_type and entity_type != "All":
            if entity_type == "Pvt Ltd":
                conditions.append("(LOWER(canonical_name) LIKE '%pvt%' OR LOWER(canonical_name) LIKE '%private%')")
            elif entity_type == "Public Ltd":
                conditions.append("(LOWER(canonical_name) LIKE '%ltd%' AND LOWER(canonical_name) NOT LIKE '%pvt%' AND LOWER(canonical_name) NOT LIKE '%private%')")
            elif entity_type == "LLP":
                conditions.append("LOWER(canonical_name) LIKE '%llp%'")
            elif entity_type == "Proprietorship / Firm":
                conditions.append("(LOWER(canonical_name) NOT LIKE '%ltd%' AND LOWER(canonical_name) NOT LIKE '%pvt%')")

        if has_email:
            conditions.append("emails != '[]' AND emails != ''")
        if has_phone:
            conditions.append("phones != '[]' AND phones != ''")
        if has_website:
            conditions.append("website != ''")

        sql = f"SELECT * FROM companies WHERE {' AND '.join(conditions)} ORDER BY panel_no ASC, canonical_name ASC LIMIT {limit};"
        return self._query_local(sql, params)

    # =========================================================================
    # DEDUPLICATION & UPSERT
    # =========================================================================

    def check_fuzzy_duplicate(
        self,
        canonical_name: str,
        cached_existing: Optional[List[Dict[str, Any]]] = None,
        similarity_threshold: float = 90.0
    ) -> Optional[Dict[str, Any]]:
        if not canonical_name or not HAS_RAPIDFUZZ:
            return None

        existing = cached_existing if cached_existing is not None else self._query_local(
            "SELECT id, canonical_name, pincode FROM companies LIMIT 200"
        )
        norm_incoming = canonical_name.strip().lower()

        for item in existing:
            db_name = item.get("canonical_name", "")
            norm_db = db_name.strip().lower()
            if norm_incoming == norm_db:
                continue

            score = fuzz.token_sort_ratio(norm_incoming, norm_db)
            if score >= similarity_threshold:
                return {
                    "existing_id": item.get("id"),
                    "existing_name": db_name,
                    "incoming_name": canonical_name,
                    "similarity_score": score,
                    "pincode": item.get("pincode", "")
                }
        return None

    def log_possible_duplicate(self, incoming_comp: dict, match_info: dict):
        sql = "INSERT INTO possible_duplicates (id, incoming_name, existing_name, similarity_score, pincode, incoming_data, status) VALUES (?, ?, ?, ?, ?, ?, 'pending');"
        dup_id = str(uuid.uuid4())
        params = [
            dup_id, match_info.get("incoming_name", ""), match_info.get("existing_name", ""),
            float(match_info.get("similarity_score", 0.0)), str(match_info.get("pincode", "")),
            json.dumps(incoming_comp)
        ]
        self._query_local(sql, params)
        self.query(sql, params)

    def insert_company_smart(
        self,
        comp: dict,
        cached_existing: Optional[List[Dict[str, Any]]] = None,
        fuzzy_check: bool = True,
        threshold: float = 90.0
    ) -> bool:
        raw_name = comp.get("raw_name") or comp.get("canonical_name") or "Unknown Entity"
        canonical_name = comp.get("canonical_name") or raw_name
        panel_no = comp.get("panel_no")
        pincode = comp.get("pincode")

        if fuzzy_check:
            fuzzy_match = self.check_fuzzy_duplicate(canonical_name, cached_existing=cached_existing, similarity_threshold=threshold)
            if fuzzy_match:
                self.log_possible_duplicate(comp, fuzzy_match)
                return False

        norm_name = re.sub(r'\b(pvt|private|ltd|limited|inc|co|corp|corporation)\b', '', canonical_name, flags=re.IGNORECASE)
        norm_name = " ".join(re.sub(r'[^a-zA-Z0-9\s]', '', norm_name).lower().split())

        aliases = comp.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = []

        existing_id = None
        if cached_existing:
            for item in cached_existing:
                if (panel_no and str(item.get("panel_no")) == str(panel_no)) or (item.get("canonical_name", "").lower() == canonical_name.lower()):
                    existing_id = item.get("id")
                    break
        else:
            existing = []
            if panel_no and int(panel_no) > 0:
                existing = self._query_local("SELECT id FROM companies WHERE panel_no = ?", [int(panel_no)])
            if not existing and canonical_name:
                existing = self._query_local("SELECT id FROM companies WHERE canonical_name = ?", [canonical_name])
            if existing:
                existing_id = existing[0]["id"]

        if existing_id:
            sql_update = """
                UPDATE companies SET
                    panel_no = ?, raw_name = ?, canonical_name = ?, normalized_name = ?, aliases = ?,
                    address = ?, pincode = ?, website = ?, phones = ?, emails = ?,
                    representatives = ?, nature_of_business = ?
                WHERE id = ?;
            """
            params_update = [
                panel_no, raw_name, canonical_name, norm_name, json.dumps(aliases),
                comp.get("address", ""), comp.get("pincode", ""), comp.get("website", ""),
                json.dumps(comp.get("phones", [])), json.dumps(comp.get("emails", [])),
                json.dumps(comp.get("representatives", [])), comp.get("nature_of_business", ""),
                existing_id
            ]
            self._query_local(sql_update, params_update)
            self.query(sql_update, params_update)
        else:
            comp_id = str(uuid.uuid4())
            sql_insert = """
                INSERT INTO companies (
                    id, panel_no, raw_name, canonical_name, normalized_name, aliases,
                    address, pincode, website, phones, emails, representatives, nature_of_business
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """
            params_insert = [
                comp_id, panel_no, raw_name, canonical_name, norm_name, json.dumps(aliases),
                comp.get("address", ""), comp.get("pincode", ""), comp.get("website", ""),
                json.dumps(comp.get("phones", [])), json.dumps(comp.get("emails", [])),
                json.dumps(comp.get("representatives", [])), comp.get("nature_of_business", "")
            ]
            self._query_local(sql_insert, params_insert)
            self.query(sql_insert, params_insert)

        return True

    def bulk_insert_companies(self, companies: list, fuzzy_check: bool = True, threshold: float = 90.0) -> int:
        inserted_count = 0
        cached_existing = self._query_local("SELECT id, panel_no, canonical_name, pincode FROM companies")

        for idx, comp in enumerate(companies):
            success = self.insert_company_smart(
                comp,
                cached_existing=cached_existing,
                fuzzy_check=fuzzy_check,
                threshold=threshold
            )
            if success:
                inserted_count += 1
                cached_existing.append({
                    "id": str(uuid.uuid4()),
                    "panel_no": comp.get("panel_no"),
                    "canonical_name": comp.get("canonical_name", ""),
                    "pincode": comp.get("pincode", "")
                })

        return inserted_count

    def get_pending_duplicates(self) -> List[Dict[str, Any]]:
        return self._query_local("SELECT * FROM possible_duplicates WHERE status = 'pending' ORDER BY created_at DESC")

    def resolve_duplicate(self, dup_id: str, action: str, comp_data: Optional[dict] = None):
        if action == "force_insert" and comp_data:
            self.insert_company_smart(comp_data, fuzzy_check=False)
        self._query_local("UPDATE possible_duplicates SET status = ? WHERE id = ?", [action, dup_id])
        self.query("UPDATE possible_duplicates SET status = ? WHERE id = ?", [action, dup_id])