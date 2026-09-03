# app.py
"""
Enterprise MSME Directory & Business Intelligence Portal.
Theme: Modern Executive Light Mode (High Contrast & Clean Typography)
Features:
- Responsive 2-Column Side-by-Side Card Grid (Widescreen Optimized)
- Compact Side-by-Side Search Bar & Dropdown Command Center
- Instant First-Screen View (Zero Unnecessary Scrolling)
- Role-Based Access Control (Admin vs Standard User)
- Light-Themed Executive Cards with Direct Action Triggers
"""

import streamlit as st
import pymupdf as fitz
from PIL import Image
import io
import json
import re
import time
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
    initial_sidebar_state="collapsed"
)

# Modern Executive Light Mode CSS
st.markdown("""
<style>
    /* Global Light Background */
    .stApp {
        background-color: #F8FAFC;
        color: #0F172A;
    }

    /* Metric Cards */
    .metric-card {
        background: linear-gradient(135deg, #FFFFFF 0%, #F1F5F9 100%);
        padding: 14px;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        color: #0F172A;
        text-align: center;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(2, 132, 199, 0.12);
        border-color: #38BDF8;
    }
    .metric-val {
        font-size: 1.6rem;
        font-weight: 800;
        background: linear-gradient(90deg, #0284C7, #4F46E5);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .metric-lbl {
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #64748B;
        font-weight: 600;
        margin-top: 3px;
    }

    /* 2-Column Side-by-Side Executive Card */
    .company-card-grid {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 18px 20px;
        margin-bottom: 16px;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.04);
        transition: border-color 0.2s ease, transform 0.15s ease, box-shadow 0.2s ease;
        min-height: 100%;
    }
    .company-card-grid:hover {
        border-color: #0284C7;
        box-shadow: 0 8px 24px rgba(2, 132, 199, 0.12);
        transform: translateY(-2px);
    }
    
    /* Badges */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.72rem;
        font-weight: 600;
        margin-right: 6px;
        letter-spacing: 0.02em;
    }
    .badge-panel { background: linear-gradient(90deg, #0284C7, #0369A1); color: white; }
    .badge-pin { background: linear-gradient(90deg, #D97706, #B45309); color: white; }

    /* Executive Pills */
    .exec-pill {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-left: 3px solid #0284C7;
        border-radius: 6px;
        padding: 8px 12px;
        margin-top: 6px;
        font-size: 0.85rem;
        color: #1E293B;
    }
    
    /* Action Buttons */
    .action-btn {
        text-decoration: none;
        background-color: #F1F5F9;
        border: 1px solid #CBD5E1;
        color: #0369A1 !important;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-right: 5px;
        margin-top: 4px;
        display: inline-block;
        transition: all 0.2s ease;
    }
    .action-btn:hover {
        background-color: #0284C7;
        color: #FFFFFF !important;
        border-color: #0284C7;
    }

    /* Auth Box */
    .auth-container {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 24px;
        box-shadow: 0 10px 25px rgba(0, 0, 0, 0.06);
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
if "search_input_val" not in st.session_state:
    st.session_state.search_input_val = ""

rotator = st.session_state.rotator
vision_agent = VisionExtractionAgent(rotator)


# ==============================================================================
# 🔐 AUTHENTICATION GATEWAY (Light Mode)
# ==============================================================================

if not st.session_state.authenticated:
    st.markdown("<h2 style='text-align: center; margin-top: 40px; color: #0F172A;'>🏢 MSME Directory Executive Portal</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #64748B;'>Enterprise Contact & Entity Disambiguation Platform</p>", unsafe_allow_html=True)

    col_center = st.columns([1, 2, 1])[1]

    with col_center:
        st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
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
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

            

        with auth_tab_register:
            st.subheader("Register Account")
            reg_name = st.text_input("Full Name", key="r_name")
            reg_username = st.text_input("Username", key="r_user")
            reg_password = st.text_input("Password", type="password", key="r_pwd")

            if st.button("✨ Register", use_container_width=True):
                if reg_username and reg_password:
                    if db.create_user(reg_username, reg_password, role="user", full_name=reg_name):
                        st.success("Account created successfully! Please sign in.")
                    else:
                        st.error("Username already exists.")
                else:
                    st.warning("All fields are required.")
        
        st.markdown("</div>", unsafe_allow_html=True)

    st.stop()


# ==============================================================================
# 👤 TOP NAVIGATION & CLOUD PIPELINE STATUS (Light Mode)
# ==============================================================================

current_user = st.session_state.user_info
is_admin = current_user.get("role") == "admin"

c_head_left, c_head_right = st.columns([3, 1])

with c_head_left:
    st.markdown(f"### 🏢 MSME Executive Directory Portal")
    st.caption(f"Logged in as **{current_user.get('full_name') or current_user.get('username')}** ({'🛡️ Master Administrator' if is_admin else '👥 Standard User'})")

with c_head_right:
    if st.button("🚪 Log Out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_info = None
        st.rerun()

pipe_status = db.get_pipeline_status()
col_pipe_info, col_pipe_btn = st.columns([3, 1])

with col_pipe_info:
    status_icon = "🟢" if pipe_status["cloud_online"] else "🟡"
    st.info(f"{status_icon} **Cloudflare D1 Pipeline:** `{pipe_status['cloud_count']} Cloud Records` | **Local Storage:** `{pipe_status['local_count']} Clean Records Loaded`")

with col_pipe_btn:
    if is_admin:
        if st.button("🔄 Sync with Cloudflare D1", use_container_width=True):
            with st.spinner("Synchronizing records from Cloudflare D1..."):
                synced_cnt, msg = db.sync_from_cloudflare_d1()
                if synced_cnt > 0:
                    st.success(msg)
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning(msg)

st.divider()


# ==============================================================================
# 🗂️ TAB CONFIGURATION BY ROLE
# ==============================================================================

if is_admin:
    tab_search, tab_ingest, tab_import, tab_review, tab_users = st.tabs([
        "🔍 Directory & Intelligence",
        "📤 Ingest Directory PDF (Admin)",
        "📁 Import Files (Admin)",
        "🛠️ Human Review & Audit (Admin)",
        "👥 User Management (Admin)"
    ])
else:
    tab_search, = st.tabs(["🔍 Directory & Intelligence"])


# ==============================================================================
# TAB 1: 2-COLUMN LIGHT THEMED DIRECTORY INTELLIGENCE
# ==============================================================================
with tab_search:
    # 1. COMPACT LIGHT KPI STRIP
    kpis = db.get_portal_kpis()
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['total_companies']}</div><div class='metric-lbl'>🏢 Verified Entities</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['phones_count']}</div><div class='metric-lbl'>📞 Phone Lines</div></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['emails_count']}</div><div class='metric-lbl'>✉️ Corporate Emails</div></div>", unsafe_allow_html=True)
    with c4:
        st.markdown(f"<div class='metric-card'><div class='metric-val'>{kpis['unique_pincodes']}</div><div class='metric-lbl'>📮 Postal Hubs</div></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # 2. SIDE-BY-SIDE SEARCH & FILTER COMMAND BAR
    col_search, col_sector, col_entity, col_sort = st.columns([4, 2.5, 2.2, 2.3])

    with col_search:
        f_search = st.text_input(
            "Search Keyword",
            value=st.session_state.search_input_val,
            placeholder="🔍 Search company name, director, keyword (e.g. 'Apex', 'Biological')...",
            label_visibility="collapsed"
        )

    with col_sector:
        f_sector = st.selectbox(
            "Industry",
            ["All Sectors", "Pharmaceuticals", "Chemicals", "Steel / Iron", "Plastics / Polymers",
             "Food / Agro", "Engineering / Fabrication", "Electronics", "Textiles / Cotton",
             "Solar / Energy", "Packaging"],
            label_visibility="collapsed"
        )
        sector_filter_val = "All" if f_sector == "All Sectors" else f_sector

    with col_entity:
        f_entity = st.selectbox(
            "Structure",
            ["All Structures", "Pvt Ltd", "Public Ltd", "LLP", "Proprietorship / Firm"],
            label_visibility="collapsed"
        )
        entity_filter_val = "All" if f_entity == "All Structures" else f_entity

    with col_sort:
        f_sort = st.selectbox(
            "Sort Order",
            ["Panel # (Asc)", "Panel # (Desc)", "Name (A-Z)", "Name (Z-A)"],
            label_visibility="collapsed"
        )

    # 3. COMPACT SECONDARY FILTER STRIP
    col_loc, col_pin, col_em, col_ph, col_wb, col_rst = st.columns([3, 2, 1.4, 1.4, 1.4, 1.2])

    with col_loc:
        f_location = st.text_input("Area", placeholder="📍 City / District / Area...", label_visibility="collapsed")

    with col_pin:
        f_pincode = st.text_input("Pincode", placeholder="📮 Pincode (e.g. 500072)", label_visibility="collapsed")

    with col_em:
        f_has_email = st.checkbox("Email ✉️")

    with col_ph:
        f_has_phone = st.checkbox("Phone 📞")

    with col_wb:
        f_has_web = st.checkbox("Web 🌐")

    with col_rst:
        if st.button("🧹 Reset", use_container_width=True):
            st.session_state.search_input_val = ""
            st.rerun()

    # 4. EXECUTE QUERY
    results = db.filter_companies_advanced(
        search_query=f_search,
        sector_keyword=sector_filter_val,
        location_keyword=f_location,
        pincode_keyword=f_pincode,
        entity_type=entity_filter_val,
        has_email=f_has_email,
        has_phone=f_has_phone,
        has_website=f_has_web,
        limit=300
    )

    # Dynamic Sorting
    if results:
        if f_sort == "Panel # (Asc)":
            results.sort(key=lambda x: (x.get("panel_no") is None, x.get("panel_no") or 0))
        elif f_sort == "Panel # (Desc)":
            results.sort(key=lambda x: (x.get("panel_no") is None, x.get("panel_no") or 0), reverse=True)
        elif f_sort == "Name (A-Z)":
            results.sort(key=lambda x: (x.get("canonical_name") or "").lower())
        elif f_sort == "Name (Z-A)":
            results.sort(key=lambda x: (x.get("canonical_name") or "").lower(), reverse=True)

    # 5. MATCH COUNT & EXPORT TOOLBAR
    col_res_header, col_csv, col_json = st.columns([3, 1, 1])
    
    with col_res_header:
        st.markdown(f"#### 🏢 Matches ({len(results)} Entities Found)")

    with col_csv:
        if results:
            df_export = pd.DataFrame(results)
            csv_data = df_export.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export CSV",
                data=csv_data,
                file_name="msme_directory_export.csv",
                mime="text/csv",
                use_container_width=True
            )

    with col_json:
        if results:
            json_data = json.dumps(results, indent=2).encode('utf-8')
            st.download_button(
                label="📥 Export JSON",
                data=json_data,
                file_name="msme_directory_export.json",
                mime="application/json",
                use_container_width=True
            )

    # 6. RENDER LIGHT-THEMED CARDS IN 2-COLUMN SIDE-BY-SIDE GRID
    if not results:
        if kpis["total_companies"] == 0:
            st.warning("⚠️ No records loaded. Please click **'🔄 Sync with Cloudflare D1'** at the top or import files!")
        else:
            st.info("No enterprise records match your search criteria. Try clearing some filters.")
    else:
        for row_idx in range(0, len(results), 2):
            grid_cols = st.columns(2)

            for col_i in range(2):
                if row_idx + col_i < len(results):
                    item = results[row_idx + col_i]
                    canonical_name = item.get("canonical_name", "Unknown Entity")
                    panel_no = item.get("panel_no") or "N/A"
                    pincode = item.get("pincode") or ""
                    address = item.get("address") or "Address not specified."
                    website = item.get("website") or ""
                    nature = item.get("nature_of_business") or "General Enterprise"

                    emails = json.loads(item.get("emails") or "[]")
                    phones = json.loads(item.get("phones") or "[]")
                    reps = json.loads(item.get("representatives") or "[]")

                    with grid_cols[col_i]:
                        st.markdown(f"""
                        <div class="company-card-grid">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px;">
                                <div>
                                    <span class="badge badge-panel">Panel #{panel_no}</span>
                                    <span class="badge badge-pin">📮 {pincode if pincode else 'India'}</span>
                                    <h4 style="margin: 6px 0 2px 0; color: #0F172A; font-weight: 700;">{canonical_name}</h4>
                                    <p style="color: #64748B; font-size: 0.85rem; margin: 0;">📍 {address}</p>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        c_info, c_reps = st.columns([1, 1])

                        with c_info:
                            st.markdown("<div style='font-size: 0.8rem; font-weight: 700; color: #475569;'>Enterprise Scope:</div>", unsafe_allow_html=True)
                            st.caption(nature)

                            if website:
                                st.markdown(f"<a href='http://{website.replace('http://', '').replace('https://', '')}' target='_blank' class='action-btn'>🌐 {website}</a>", unsafe_allow_html=True)

                            if emails:
                                st.markdown("<div style='font-size: 0.78rem; font-weight: 700; color: #475569; margin-top: 4px;'>✉️ Verified Emails:</div>", unsafe_allow_html=True)
                                for em in emails[:2]:
                                    st.markdown(f"<a href='mailto:{em}' class='action-btn'>✉️ {em}</a>", unsafe_allow_html=True)

                            if phones:
                                st.markdown("<div style='font-size: 0.78rem; font-weight: 700; color: #475569; margin-top: 4px;'>📞 Telephones:</div>", unsafe_allow_html=True)
                                for ph in phones[:2]:
                                    st.markdown(f"<a href='tel:{ph}' class='action-btn'>📞 {ph}</a>", unsafe_allow_html=True)

                        with c_reps:
                            st.markdown("<div style='font-size: 0.8rem; font-weight: 700; color: #475569;'>👥 Key Executives:</div>", unsafe_allow_html=True)
                            if reps and isinstance(reps, list):
                                for r in reps[:3]:
                                    r_name = r.get("name", "Executive")
                                    r_desig = r.get("designation") or "Executive / Director"
                                    r_mob = r.get("mobile") or ""

                                    st.markdown(f"""
                                    <div class="exec-pill">
                                        <strong>👤 {r_name}</strong> <span style="color: #0284C7; font-size: 0.75rem; font-weight: 600;">({r_desig})</span>
                                        {f"<br><a href='tel:{r_mob}' class='action-btn' style='margin-top: 4px;'>📞 {r_mob}</a>" if r_mob else ""}
                                    </div>
                                    """, unsafe_allow_html=True)
                            else:
                                st.caption("No executives explicitly listed.")

                        st.markdown("<br>", unsafe_allow_html=True)


# ==============================================================================
# ADMIN TABS (Only Visible to Administrators)
# ==============================================================================

if is_admin:
    # --------------------------------------------------------------------------
    # TAB 2: PDF VISION PIPELINE
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
            st.rerun()

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
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to import file: {e}")

    # --------------------------------------------------------------------------
    # TAB 4: HUMAN REVIEW & AUDIT QUEUE
    # --------------------------------------------------------------------------
    with tab_review:
        st.subheader("🛠️ Human Review & Audit Queue")

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
    # TAB 5: USER MANAGEMENT
    # --------------------------------------------------------------------------
    with tab_users:
        st.subheader("👥 User Management Console")

        with st.expander("➕ Create New User / Administrator"):
            u_name = st.text_input("Full Name", key="u_name")
            u_user = st.text_input("Username", key="u_user")
            u_pwd = st.text_input("Password", type="password", key="u_pwd")
            u_role = st.selectbox("Role Permission", ["user", "admin"])

            if st.button("Create Account"):
                if u_user and u_pwd:
                    if db.create_user(u_user, u_pwd, role=u_role, full_name=u_name):
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
