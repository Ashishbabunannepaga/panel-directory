# app.py
"""
Enterprise MSME Directory Portal & Entity Resolution Engine.
Features:
- Role-Based Access Control (Admin vs Standard User)
- User Authentication & Registration Gateway
- Executive Summary KPI Dashboard
- Multi-Criteria Search & Filter Sidebar
- Rich Executive Cards with Direct Action Triggers
- Ingestion & Human Review Tabs (Admin Only)
"""

import streamlit as st
import pymupdf as fitz
from PIL import Image
import io
import json
import re
import pandas as pd

from key_rotator import GeminiKeyRotator
from cloudflare_db import CloudflareD1
from agent_engine import (
    ColumnSplitter,
    VisionExtractionAgent,
    merge_continuation_records,
    check_panel_continuity,
    DisambiguationAgent,
    QualityAuditAgent
)

# Page Configuration
st.set_page_config(
    page_title="MSME Executive Directory Portal",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Modern Executive Card Styling
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #334155;
        color: #F8FAFC;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .metric-val {
        font-size: 2rem;
        font-weight: 700;
        color: #38BDF8;
    }
    .metric-lbl {
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #94A3B8;
    }
    .company-card {
        background-color: #0F172A;
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 22px;
        margin-bottom: 20px;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2);
    }
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 6px;
    }
    .badge-panel { background-color: #0284C7; color: white; }
    .badge-entity { background-color: #0D9488; color: white; }
    .badge-pin { background-color: #D97706; color: white; }
    .exec-pill {
        background-color: #1E293B;
        border: 1px solid #475569;
        border-radius: 8px;
        padding: 10px 14px;
        margin-top: 8px;
    }
    .action-btn {
        text-decoration: none;
        background-color: #334155;
        color: #38BDF8 !important;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.8rem;
        margin-right: 8px;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

# Fetch Credentials
GEMINI_KEYS = st.secrets.get("GEMINI_API_KEYS", [])
CF_ACCOUNT_ID = st.secrets.get("CLOUDFLARE_ACCOUNT_ID", "")
CF_DATABASE_ID = st.secrets.get("CLOUDFLARE_DATABASE_ID", "")
CF_API_TOKEN = st.secrets.get("CLOUDFLARE_API_TOKEN", "")

if not GEMINI_KEYS or not CF_ACCOUNT_ID or not CF_DATABASE_ID or not CF_API_TOKEN:
    st.error("⚠️ Secrets missing in `.streamlit/secrets.toml`!")
    st.stop()

# Initialize Database & State
db = CloudflareD1(CF_ACCOUNT_ID, CF_DATABASE_ID, CF_API_TOKEN)

if "rotator" not in st.session_state:
    st.session_state.rotator = GeminiKeyRotator(GEMINI_KEYS)
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None
if "review_queue" not in st.session_state:
    st.session_state.review_queue = []
if "page_audit_logs" not in st.session_state:
    st.session_state.page_audit_logs = []

rotator = st.session_state.rotator
vision_agent = VisionExtractionAgent(rotator)


# ==============================================================================
# 🔐 AUTHENTICATION & LOGIN GATEWAY
# ==============================================================================

if not st.session_state.authenticated:
    st.markdown("<h2 style='text-align: center;'>🏢 MSME Directory Executive Portal</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #94A3B8;'>Enterprise Contact & Entity Disambiguation Platform</p>", unsafe_allow_html=True)

    col_center = st.columns([1, 2, 1])[1]

    with col_center:
        auth_tab_login, auth_tab_register = st.tabs(["🔑 Sign In", "📝 Create User Account"])

        with auth_tab_login:
            st.subheader("Login to Portal")
            login_username = st.text_input("Username", key="l_user")
            login_password = st.text_input("Password", type="password", key="l_pwd")

            if st.button("🚀 Sign In", use_container_width=True):
                user = db.authenticate_user(login_username, login_password)
                if user:
                    st.session_state.authenticated = True
                    st.session_state.user_info = user
                    st.success(f"Welcome back, {user.get('full_name') or user.get('username')}!")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

            

        with auth_tab_register:
            st.subheader("Register New User")
            reg_name = st.text_input("Full Name", key="r_name")
            reg_username = st.text_input("Username", key="r_user")
            reg_password = st.text_input("Password", type="password", key="r_pwd")

            if st.button("✨ Register Account", use_container_width=True):
                if reg_username and reg_password:
                    success = db.create_user(reg_username, reg_password, role="user", full_name=reg_name)
                    if success:
                        st.success("Account created successfully! You may now sign in.")
                    else:
                        st.error("Username already exists or registration failed.")
                else:
                    st.warning("Please fill in all required fields.")

    st.stop()


# ==============================================================================
# 👤 LOGGED-IN SIDEBAR & NAVIGATION
# ==============================================================================

current_user = st.session_state.user_info
is_admin = current_user.get("role") == "admin"

with st.sidebar:
    st.markdown(f"### 👤 Logged in as: **{current_user.get('full_name') or current_user.get('username')}**")
    st.caption(f"Role: `{'🛡️ Master Administrator' if is_admin else '👥 Standard User'}`")

    if st.button("🚪 Log Out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_info = None
        st.rerun()

    st.divider()
    st.markdown("### 🔍 Multi-Faceted Filters")

    f_search = st.text_input("Global Keyword Search", placeholder="e.g. Apex, Satish, TMT...")

    f_sector = st.selectbox("Industry / Sector", [
        "All", "Pharmaceuticals", "Chemicals", "Steel / Iron", "Plastics / Polymers",
        "Food / Agro", "Engineering / Fabrication", "Electronics", "Textiles / Cotton",
        "Solar / Energy", "Packaging"
    ])

    f_entity = st.selectbox("Entity Structure", ["All", "Pvt Ltd", "Public Ltd", "LLP", "Proprietorship / Firm"])
    f_location = st.text_input("City / District / Area", placeholder="e.g. Sangareddy, Mumbai, Jeedimetla")
    f_pincode = st.text_input("Pincode", placeholder="e.g. 500072")

    st.markdown("**Contact Requirements:**")
    f_has_email = st.checkbox("Must Have Email ✉️")
    f_has_phone = st.checkbox("Must Have Phone 📞")
    f_has_web = st.checkbox("Must Have Website 🌐")


# ==============================================================================
# 🗂️ TAB CONFIGURATION BY USER ROLE
# ==============================================================================

if is_admin:
    tab_search, tab_ingest, tab_import, tab_review, tab_users = st.tabs([
        "🔍 Search & Intelligence",
        "📤 Ingest Directory PDF (Admin)",
        "📁 Import Files (Admin)",
        "🛠️ Human Review & Audit (Admin)",
        "👥 User Management (Admin)"
    ])
else:
    # Standard users get strictly the Search & Intelligence Tab
    tab_search, = st.tabs(["🔍 Search & Intelligence"])


# ==============================================================================
# TAB 1: SEARCH & EXECUTIVE INTELLIGENCE (Visible to All Users)
# ==============================================================================
with tab_search:
    # 1. KPI Dashboard
    kpis = db.get_portal_kpis()
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['total_companies']}</div><div class='metric-lbl'>Total Entities</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['phones_count']}</div><div class='metric-lbl'>Verified Contact Lines</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['emails_count']}</div><div class='metric-lbl'>Verified Emails</div></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['unique_pincodes']}</div><div class='metric-lbl'>Postal Hubs</div></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # 2. Query Filtering
    with st.spinner("Filtering Enterprise Records..."):
        results = db.filter_companies_advanced(
            search_query=f_search,
            sector_keyword=f_sector,
            location_keyword=f_location,
            pincode_keyword=f_pincode,
            entity_type=f_entity,
            has_email=f_has_email,
            has_phone=f_has_phone,
            has_website=f_has_web,
            limit=200
        )

    # 3. Action Toolbar (Exporting)
    col_res_header, col_export = st.columns([3, 1])
    with col_res_header:
        st.subheader(f"🏢 Search Results ({len(results)} Matches)")
    with col_export:
        if results:
            df_export = pd.DataFrame(results)
            csv_data = df_export.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Results (CSV)",
                data=csv_data,
                file_name="msme_directory_export.csv",
                mime="text/csv",
                use_container_width=True
            )

    # 4. Rich Executive Card Rendering
    if not results:
        st.info("No enterprise records matched the selected filter criteria. Try broadening your search.")
    else:
        for item in results:
            canonical_name = item.get("canonical_name", "Unknown Entity")
            panel_no = item.get("panel_no") or "N/A"
            pincode = item.get("pincode") or ""
            address = item.get("address") or "Address not provided."
            website = item.get("website") or ""
            nature = item.get("nature_of_business") or "General Enterprise"

            emails = json.loads(item.get("emails") or "[]")
            phones = json.loads(item.get("phones") or "[]")
            reps = json.loads(item.get("representatives") or "[]")

            with st.container():
                st.markdown(f"""
                <div class="company-card">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                        <div>
                            <span class="badge badge-panel">Panel #{panel_no}</span>
                            <span class="badge badge-pin">📮 {pincode if pincode else 'India'}</span>
                            <h3 style="margin: 8px 0 4px 0; color: #F8FAFC;">{canonical_name}</h3>
                            <p style="color: #94A3B8; font-size: 0.9rem; margin: 0;">📍 {address}</p>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                col_info, col_reps = st.columns([1, 1])

                with col_info:
                    st.markdown("**Enterprise Focus & Contact Lines:**")
                    st.info(nature)

                    if website:
                        st.markdown(f"<a href='http://{website.replace('http://', '').replace('https://', '')}' target='_blank' class='action-btn'>🌐 {website}</a>", unsafe_allow_html=True)

                    if emails:
                        st.write("✉️ **Emails:**")
                        for em in emails:
                            st.markdown(f"<a href='mailto:{em}' class='action-btn'>✉️ {em}</a>", unsafe_allow_html=True)

                    if phones:
                        st.write("📞 **Telephones / Office:**")
                        for ph in phones:
                            st.markdown(f"<a href='tel:{ph}' class='action-btn'>📞 {ph}</a>", unsafe_allow_html=True)

                with col_reps:
                    st.markdown("**👥 Key Executives & Directors:**")
                    if reps and isinstance(reps, list):
                        for r in reps:
                            r_name = r.get("name", "Executive")
                            r_desig = r.get("designation") or "Director / Representative"
                            r_mob = r.get("mobile") or ""

                            st.markdown(f"""
                            <div class="exec-pill">
                                <strong>👤 {r_name}</strong> <span style="color: #38BDF8; font-size: 0.8rem;">({r_desig})</span>
                                {f"<br><a href='tel:{r_mob}' class='action-btn' style='margin-top: 4px;'>📞 Direct: {r_mob}</a>" if r_mob else ""}
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.caption("No key executives explicitly listed.")

                st.divider()


# ==============================================================================
# ADMIN TABS (Only Rendered if is_admin == True)
# ==============================================================================

if is_admin:
    # --------------------------------------------------------------------------
    # TAB 2: PDF VISION INGESTION
    # --------------------------------------------------------------------------
    with tab_ingest:
        st.subheader("📤 Agentic Multi-Column PDF Pipeline")
        uploaded_pdf = st.file_uploader("Upload Directory PDF", type=["pdf"])
        enable_double_pass = st.checkbox("Enable Double-Pass Verification (Diffing)", value=True)

        if uploaded_pdf and st.button("🚀 Execute PDF Pipeline"):
            doc = fitz.open(stream=uploaded_pdf.read(), filetype="pdf")
            total_pages = len(doc)
            progress_bar = st.progress(0)
            status_box = st.empty()

            all_extracted_blocks = []
            st.session_state.page_audit_logs = []

            for page_idx in range(total_pages):
                page_num = page_idx + 1
                status_box.text(f"Processing Page {page_num} of {total_pages} (Splitting Columns & OCR)...")

                page = doc.load_page(page_idx)
                pix = page.get_pixmap(dpi=150)
                page_img = Image.open(io.BytesIO(pix.tobytes("png")))

                column_strips = ColumnSplitter.split_page(page_img, page_num=page_num, num_columns=3)

                for strip in column_strips:
                    if enable_double_pass:
                        blocks = vision_agent.double_pass_extract(strip)
                    else:
                        blocks = vision_agent.extract_from_column_strip(strip)

                    for b in blocks:
                        b["crop_image"] = strip["image"]

                    all_extracted_blocks.extend(blocks)

                progress_bar.progress((page_idx + 1) / total_pages)

            status_box.text("Merging multi-page continuation records...")
            merged_records = merge_continuation_records(all_extracted_blocks)
            st.session_state.page_audit_logs = check_panel_continuity(merged_records)

            auto_commit_batch = []
            for rec in merged_records:
                if rec.get("needs_review"):
                    st.session_state.review_queue.append(rec)
                else:
                    proc = DisambiguationAgent.process_entity(rec)
                    audited = QualityAuditAgent.audit(proc)
                    auto_commit_batch.append(audited)

            status_box.text("Writing clean records to Database...")
            committed_count = db.bulk_insert_companies(auto_commit_batch, fuzzy_check=True)

            status_box.empty()
            st.balloons()
            st.success(f"Processing Complete! Successfully committed {committed_count} clean records.")

            if st.session_state.review_queue:
                st.warning(f"⚠️ {len(st.session_state.review_queue)} records flagged for human review.")

    # --------------------------------------------------------------------------
    # TAB 3: FILE IMPORT (CSV / JSON)
    # --------------------------------------------------------------------------
    with tab_import:
        st.subheader("📁 Universal File Importer")
        file_upload = st.file_uploader("Upload `.csv` or `.json` file", type=["csv", "xlsx", "json"])

        if st.button("📥 Commit File Data"):
            if file_upload:
                filename = file_upload.name.lower()
                try:
                    if filename.endswith(".json"):
                        parsed_data = json.loads(file_upload.read().decode("utf-8"))
                    else:
                        parsed_data = pd.read_csv(file_upload, dtype=str).to_dict(orient="records")

                    cleaned_batch = []
                    for entry in parsed_data:
                        proc = DisambiguationAgent.process_entity(entry)
                        audited = QualityAuditAgent.audit(proc)
                        cleaned_batch.append(audited)

                    count = db.bulk_insert_companies(cleaned_batch, fuzzy_check=True)
                    st.success(f"Successfully ingested {count} records into the database!")
                except Exception as e:
                    st.error(f"Failed to import file: {e}")

    # --------------------------------------------------------------------------
    # TAB 4: HUMAN REVIEW & AUDIT QUEUE
    # --------------------------------------------------------------------------
    with tab_review:
        st.subheader("🛠️ Human Review & Audit Queue")

        # Discrepancy Queue
        st.markdown("### 1. OCR Extraction Discrepancies")
        review_queue = st.session_state.review_queue

        if not review_queue:
            st.info("🎉 No pending OCR discrepancies.")
        else:
            for idx, item in enumerate(list(review_queue)):
                st.markdown(f"#### Flagged Record #{idx+1} (Page {item.get('page_num')}, Col {item.get('column_index')})")
                c_img, c_diff = st.columns([1, 2])

                with c_img:
                    if "crop_image" in item:
                        st.image(item["crop_image"], caption="Source Strip Crop", use_container_width=True)

                with c_diff:
                    discrepancies = item.get("discrepancies", {})
                    resolved_fields = {}

                    for field, candidates in discrepancies.items():
                        cand_a = candidates.get("candidate_a")
                        cand_b = candidates.get("candidate_b")

                        choice = st.radio(
                            f"Select value for `{field}`:",
                            options=[f"Pass A: {cand_a}", f"Pass B: {cand_b}", "Custom Correction"],
                            key=f"rad_{idx}_{field}"
                        )

                        if choice == "Custom Correction":
                            val_chosen = st.text_input(f"Enter correct text for `{field}`:", key=f"txt_{idx}_{field}")
                        elif choice.startswith("Pass A"):
                            val_chosen = cand_a
                        else:
                            val_chosen = cand_b

                        resolved_fields[field] = val_chosen

                    if st.button(f"✅ Approve Record #{idx+1}", key=f"btn_commit_{idx}"):
                        for f_key, f_val in resolved_fields.items():
                            item[f_key] = f_val
                        item["needs_review"] = False

                        proc = DisambiguationAgent.process_entity(item)
                        audited = QualityAuditAgent.audit(proc)
                        db.insert_company_smart(audited, fuzzy_check=True)

                        st.session_state.review_queue.pop(idx)
                        st.rerun()

        st.divider()

        # Fuzzy Duplicate Queue
        st.markdown("### 2. Fuzzy Duplicates Queue")
        pending_dups = db.get_pending_duplicates()

        if not pending_dups:
            st.info("No fuzzy duplicate candidates pending review.")
        else:
            for d in pending_dups:
                with st.expander(f"⚠️ Duplicate Candidate: {d['incoming_name']} ({d['similarity_score']}% match)"):
                    st.write(f"**Incoming Name:** {d['incoming_name']}")
                    st.write(f"**Existing Database Name:** {d['existing_name']}")
                    st.write(f"**Pincode:** {d['pincode']}")

                    c_acc, c_rej = st.columns(2)
                    with c_acc:
                        if st.button("Force Insert as New Entity", key=f"force_{d['id']}"):
                            inc_data = json.loads(d["incoming_data"])
                            db.resolve_duplicate(d["id"], "force_insert", inc_data)
                            st.success("Inserted as distinct entity!")
                            st.rerun()
                    with c_rej:
                        if st.button("Dismiss / Merge", key=f"dismiss_{d['id']}"):
                            db.resolve_duplicate(d["id"], "dismiss")
                            st.info("Candidate dismissed.")
                            st.rerun()

    # --------------------------------------------------------------------------
    # TAB 5: USER MANAGEMENT (Admin Only)
    # --------------------------------------------------------------------------
    with tab_users:
        st.subheader("👥 User Management Console")
        
        # User Creation Form
        with st.expander("➕ Create New User / Administrator"):
            u_name = st.text_input("Full Name", key="u_name")
            u_user = st.text_input("Username", key="u_user")
            u_pwd = st.text_input("Password", type="password", key="u_pwd")
            u_role = st.selectbox("Role Permission", ["user", "admin"])

            if st.button("Create Account"):
                if u_user and u_pwd:
                    ok = db.create_user(u_user, u_pwd, role=u_role, full_name=u_name)
                    if ok:
                        st.success(f"User '{u_user}' successfully created!")
                        st.rerun()
                    else:
                        st.error("Username already exists.")
                else:
                    st.warning("Username and Password are required.")

        st.markdown("### Registered Users")
        user_list = db.get_all_users()
        if user_list:
            df_users = pd.DataFrame(user_list)
            st.dataframe(df_users[["username", "full_name", "role", "created_at"]], use_container_width=True)
