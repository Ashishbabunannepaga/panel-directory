# agent_engine.py
"""
Agentic Extraction Engine for MSME Directory Processing Pipeline.
Updated to modern google-genai SDK with structured output schema,
column pre-splitting, double-pass verification, and batch continuation merging.
"""

import json
import re
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image
from pydantic import BaseModel

# Modern Google GenAI SDK
from google import genai
from google.genai import types

# Optional OpenCV for adaptive vertical line detection
try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

# Optional rapidfuzz for string diffing
try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False


# ==============================================================================
# 1. COLUMN SPLITTER (Image Pre-Processing)
# ==============================================================================
class ColumnSplitter:
    """
    Pre-splits multi-column scanned directory pages into N separate column strips.
    Uses vertical line detection (OpenCV HoughLinesP) when available, falling back
    to fixed 3-column fractional splitting.
    """

    @staticmethod
    def split_page(
        image: Image.Image,
        page_num: int = 1,
        num_columns: int = 3,
        margin_overlap_pct: float = 0.01
    ) -> List[Dict[str, Any]]:
        width, height = image.size
        column_bounds = ColumnSplitter._detect_column_bounds(image, num_columns)

        column_strips = []
        for col_idx, (x_min, x_max) in enumerate(column_bounds):
            overlap_px = int(width * margin_overlap_pct)
            crop_x1 = max(0, x_min - overlap_px)
            crop_x2 = min(width, x_max + overlap_px)

            strip_img = image.crop((crop_x1, 0, crop_x2, height))

            column_strips.append({
                "page_num": page_num,
                "column_index": col_idx,
                "total_columns": len(column_bounds),
                "image": strip_img,
                "bbox": (crop_x1, 0, crop_x2, height),
                "width": crop_x2 - crop_x1,
                "height": height
            })

        return column_strips

    @staticmethod
    def _detect_column_bounds(image: Image.Image, fallback_cols: int = 3) -> List[Tuple[int, int]]:
        width, height = image.size

        if HAS_OPENCV:
            try:
                img_np = np.array(image.convert("RGB"))
                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                edges = cv2.Canny(gray, 50, 150, apertureSize=3)

                min_line_len = int(height * 0.4)
                lines = cv2.HoughLinesP(
                    edges, 1, np.pi / 180, threshold=100,
                    minLineLength=min_line_len, maxLineGap=20
                )

                vert_x_coords = []
                if lines is not None:
                    for line in lines:
                        # Fix: use ravel() to flatten coordinate array safely
                        coords = line.ravel()
                        if len(coords) >= 4:
                            x1, y1, x2, y2 = int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])
                            if abs(x1 - x2) <= 10 and abs(y1 - y2) >= min_line_len:
                                if 0.1 * width < x1 < 0.9 * width:
                                    vert_x_coords.append(x1)

                if vert_x_coords:
                    vert_x_coords.sort()
                    dividers = []
                    last_x = -100
                    for x in vert_x_coords:
                        if x - last_x > width * 0.15:
                            dividers.append(x)
                            last_x = x

                    if len(dividers) == fallback_cols - 1:
                        bounds = []
                        starts = [0] + dividers
                        ends = dividers + [width]
                        for s, e in zip(starts, ends):
                            bounds.append((s, e))
                        return bounds
            except Exception as e:
                pass  # Fallback smoothly to 3 equal columns

        # Fallback: Fixed fractional splitting (3 equal columns)
        col_width = width / fallback_cols
        bounds = []
        for i in range(fallback_cols):
            x1 = int(i * col_width)
            x2 = int((i + 1) * col_width) if i < fallback_cols - 1 else width
            bounds.append((x1, x2))

        return bounds


# ==============================================================================
# 2. STRUCTURED GEMINI VISION AGENT (Pydantic Schema + Double-Pass)
# ==============================================================================

class ExtractedRecordModel(BaseModel):
    panel_no: Optional[int] = None
    is_continuation: bool = False
    raw_name: Optional[str] = None
    address_raw: Optional[str] = None
    phone_raw: Optional[str] = None
    email_raw: Optional[str] = None
    web_raw: Optional[str] = None
    representatives_raw: Optional[str] = None
    nb_raw: Optional[str] = None


class VisionExtractionAgent:
    """
    Extracts structured company records from column strip images using google-genai
    typed response_schema with double-pass verification support.
    """

    def __init__(self, key_rotator):
        self.rotator = key_rotator

    def extract_from_column_strip(
        self,
        column_meta: Dict[str, Any],
        model_name: str = "gemini-3.5-flash"
    ) -> List[Dict[str, Any]]:
        """Single structured extraction call using modern genai.Client."""
        client = self.rotator.get_client()

        prompt = """
        You are an expert OCR and Data Extraction AI processing ONE VERTICAL COLUMN of an MSME Directory.

        INSTRUCTIONS:
        1. Process the image TOP-TO-BOTTOM.
        2. A bold panel number (e.g. 142, 153, 154) indicates the start of a company entry.
        3. If the top of the image starts with text without a Panel Number (e.g. continuation from previous column), set "panel_no": null and "is_continuation": true.
        4. Capture labeled text accurately:
           - 'Ph' / Phone numbers -> phone_raw
           - 'Email' -> email_raw
           - 'Web' -> web_raw
           - 'Rep.' -> representatives_raw
           - 'NB' -> nb_raw (Nature of Business)
        5. Return ONLY a valid JSON Array conforming to the schema.
        """

        try:
            image = column_meta["image"]
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt, image],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=list[ExtractedRecordModel],
                    temperature=0.1
                )
            )

            raw_text = response.text.strip()
            records = json.loads(raw_text)

            for r in records:
                r["page_num"] = column_meta.get("page_num", 1)
                r["column_index"] = column_meta.get("column_index", 0)
                r["needs_review"] = False
                r["discrepancies"] = {}

            return records
        except Exception as e:
            print(f"[VisionExtractionAgent] Extraction failed on page {column_meta.get('page_num')} col {column_meta.get('column_index')}: {e}")
            return []

    def double_pass_extract(
        self,
        column_meta: Dict[str, Any],
        model_a: str = "gemini-3.5-flash",
        model_b: str = "gemini-3.7-flash"
    ) -> List[Dict[str, Any]]:
        """Executes double-pass verification diffing across rotated keys."""
        records_a = self.extract_from_column_strip(column_meta, model_name=model_a)
        records_b = self.extract_from_column_strip(column_meta, model_name=model_b)

        if not records_a:
            return records_b
        if not records_b:
            return records_a

        final_records = []
        fields_to_check = [
            "panel_no", "raw_name", "address_raw", "phone_raw",
            "email_raw", "web_raw", "representatives_raw", "nb_raw"
        ]

        max_len = max(len(records_a), len(records_b))
        for i in range(max_len):
            rec_a = records_a[i] if i < len(records_a) else {}
            rec_b = records_b[i] if i < len(records_b) else {}

            base_rec = dict(rec_a) if rec_a else dict(rec_b)
            discrepancies = {}
            needs_review = False

            for field in fields_to_check:
                val_a = rec_a.get(field)
                val_b = rec_b.get(field)

                if not self._fields_agree(val_a, val_b):
                    needs_review = True
                    discrepancies[field] = {
                        "candidate_a": val_a,
                        "candidate_b": val_b
                    }

            base_rec["needs_review"] = needs_review
            base_rec["discrepancies"] = discrepancies
            base_rec["page_num"] = column_meta.get("page_num", 1)
            base_rec["column_index"] = column_meta.get("column_index", 0)
            base_rec["column_bbox"] = column_meta.get("bbox")

            final_records.append(base_rec)

        return final_records

    @staticmethod
    def _fields_agree(val_a: Any, val_b: Any) -> bool:
        if val_a is None and val_b is None:
            return True
        if val_a is None or val_b is None:
            return False

        str_a = str(val_a).strip().lower()
        str_b = str(val_b).strip().lower()

        if str_a == str_b:
            return True

        if HAS_RAPIDFUZZ:
            return fuzz.token_sort_ratio(str_a, str_b) >= 92.0

        return re.sub(r"\s+", "", str_a) == re.sub(r"\s+", "", str_b)


# ==============================================================================
# 3. CONTINUATION MERGING & PANEL CONTINUITY AUDITING
# ==============================================================================

def merge_continuation_records(all_ordered_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merges continuation fragments across the full multi-page batch."""
    merged_output = []
    current_panel_record = None

    for record in all_ordered_records:
        is_cont = record.get("is_continuation", False) or (record.get("panel_no") is None)
        has_name = bool(record.get("raw_name") and str(record.get("raw_name")).strip())

        if is_cont and not has_name and current_panel_record is not None:
            if record.get("representatives_raw"):
                prev_rep = current_panel_record.get("representatives_raw") or ""
                current_panel_record["representatives_raw"] = f"{prev_rep} {record['representatives_raw']}".strip()

            if record.get("nb_raw"):
                prev_nb = current_panel_record.get("nb_raw") or ""
                current_panel_record["nb_raw"] = f"{prev_nb} {record['nb_raw']}".strip()

            if record.get("phone_raw"):
                prev_ph = current_panel_record.get("phone_raw") or ""
                current_panel_record["phone_raw"] = f"{prev_ph} {record['phone_raw']}".strip()

            if record.get("email_raw"):
                prev_em = current_panel_record.get("email_raw") or ""
                current_panel_record["email_raw"] = f"{prev_em} {record['email_raw']}".strip()

            if record.get("address_raw"):
                prev_addr = current_panel_record.get("address_raw") or ""
                current_panel_record["address_raw"] = f"{prev_addr} {record['address_raw']}".strip()

            if record.get("needs_review"):
                current_panel_record["needs_review"] = True
                current_panel_record.setdefault("discrepancies", {}).update(record.get("discrepancies", {}))
        else:
            merged_output.append(record)
            if record.get("panel_no") is not None:
                current_panel_record = record

    return merged_output


def check_panel_continuity(all_extracted_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Audits panel sequence across pages and logs potential missed panels."""
    page_logs = []
    records_by_page: Dict[int, List[int]] = {}

    for r in all_extracted_records:
        p_num = r.get("page_num", 1)
        p_no = r.get("panel_no")
        if p_no is not None:
            records_by_page.setdefault(p_num, []).append(int(p_no))

    sorted_pages = sorted(records_by_page.keys())
    global_prev_panel = None

    for page in sorted_pages:
        panels = records_by_page[page]
        panels.sort()

        has_gap = False
        gap_details = []

        if global_prev_panel is not None and panels:
            first_on_page = panels[0]
            if first_on_page > global_prev_panel + 1:
                has_gap = True
                gap_details.append(f"Page start gap: Panel {global_prev_panel} (Prev Page) -> Panel {first_on_page} (This Page)")

        for idx in range(len(panels) - 1):
            curr_p = panels[idx]
            next_p = panels[idx + 1]
            if next_p > curr_p + 1 and next_p - curr_p > 2:
                has_gap = True
                gap_details.append(f"In-page gap: Panel {curr_p} -> Panel {next_p}")

        if panels:
            global_prev_panel = panels[-1]

        page_logs.append({
            "page_num": page,
            "panel_count": len(panels),
            "panel_range": f"{panels[0]}-{panels[-1]}" if panels else "None",
            "possible_missed_panel": has_gap,
            "gap_details": gap_details
        })

    return page_logs


# ==============================================================================
# 4. DISAMBIGUATION & QUALITY AUDIT AGENTS
# ==============================================================================

class DisambiguationAgent:
    @staticmethod
    def process_entity(entry: Dict[str, Any]) -> Dict[str, Any]:
        raw_name = entry.get("raw_name") or entry.get("canonical_name") or "Unknown Entity"
        raw_name = str(raw_name).strip()

        canonical = re.sub(r"\s+", " ", raw_name)
        entry["raw_name"] = raw_name
        entry["canonical_name"] = canonical.title()

        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = []

        words = [
            w for w in canonical.split()
            if w.upper() not in ["PVT", "LTD", "LIMITED", "PRIVATE", "CO", "INC", "CORP", "(P)"]
        ]
        if len(words) > 1:
            acronym = "".join([w[0].upper() for w in words if w])
            if acronym and acronym not in aliases:
                aliases.append(acronym)

        entry["aliases"] = aliases
        return entry


class QualityAuditAgent:
    @staticmethod
    def audit(entry: Dict[str, Any]) -> Dict[str, Any]:
        address = entry.get("address") or entry.get("address_raw") or ""
        entry["address"] = str(address).strip()

        if not entry.get("pincode"):
            pin_m = re.search(r"\b\d{6}\b", entry["address"])
            if pin_m:
                entry["pincode"] = pin_m.group(0)
            else:
                entry["pincode"] = ""

        phones_raw = entry.get("phone_raw") or ""
        phones = entry.get("phones", [])
        if phones_raw and not phones:
            phones = QualityAuditAgent._parse_phone_string(str(phones_raw))
        entry["phones"] = phones

        emails_raw = entry.get("email_raw") or ""
        emails = entry.get("emails", [])
        website = entry.get("website") or entry.get("web_raw") or ""

        if emails_raw and not emails:
            for token in re.split(r"[,;\s]", str(emails_raw)):
                token = token.strip().lower()
                if "@" in token and "." in token:
                    emails.append(token)
                elif ("www." in token or token.endswith(".com") or token.endswith(".in")) and not website:
                    website = token

        entry["emails"] = list(dict.fromkeys(emails))
        entry["website"] = str(website).strip()

        reps_raw = entry.get("representatives_raw") or ""
        reps = entry.get("representatives", [])
        if reps_raw and not reps:
            reps = QualityAuditAgent._parse_reps_string(str(reps_raw))
        entry["representatives"] = reps

        nb_raw = entry.get("nb_raw") or entry.get("nature_of_business") or ""
        entry["nature_of_business"] = str(nb_raw).strip()

        return entry

    @staticmethod
    def _parse_phone_string(raw: str) -> List[str]:
        phones = []
        tokens = re.split(r"[,;&]|\s+and\s+", raw, flags=re.IGNORECASE)
        for t in tokens:
            num = re.sub(r"[^\d\+]", "", t)
            if len(num) >= 6:
                phones.append(num)
        return list(dict.fromkeys(phones))

    @staticmethod
    def _parse_reps_string(raw: str) -> List[Dict[str, str]]:
        reps = []
        lines = re.split(r"[,;\n&]", raw)
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            phone_match = re.search(r"[\-\:\s]+(\d{10}|\d{8,11})\b", line_str)
            mob = phone_match.group(1) if phone_match else ""
            clean_name = line_str.replace(phone_match.group(0), "").strip() if phone_match else line_str

            reps.append({
                "name": clean_name,
                "designation": "",
                "mobile": mob
            })
        return reps