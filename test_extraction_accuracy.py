#!/usr/bin/env python3
# test_extraction_accuracy.py
"""
Accuracy Verification Script.
Compares extracted candidate outputs field-by-field against gold_set/gold_fixtures.json
and prints a per-field accuracy percentage report.
"""

import json
import os
import sys

try:
    from rapidfuzz import fuzz
except ImportError:
    print("Please install rapidfuzz: pip install rapidfuzz")
    sys.exit(1)

GOLD_SET_PATH = os.path.join("gold_set", "gold_fixtures.json")


def calculate_field_accuracy(gold_records: list, candidate_records: list):
    total = len(gold_records)
    if total == 0:
        print("Gold set is empty!")
        return

    cand_map = {c.get("panel_no"): c for c in candidate_records if c.get("panel_no")}

    scores = {
        "canonical_name": [],
        "pincode": [],
        "address": [],
        "phones": [],
        "emails": [],
        "representatives": [],
        "nature_of_business": []
    }

    for g in gold_records:
        panel_no = g.get("panel_no")
        c = cand_map.get(panel_no, {})

        name_sim = fuzz.token_sort_ratio(g.get("canonical_name", ""), c.get("canonical_name", ""))
        scores["canonical_name"].append(name_sim)

        pin_match = 100.0 if str(g.get("pincode", "")).strip() == str(c.get("pincode", "")).strip() else 0.0
        scores["pincode"].append(pin_match)

        addr_sim = fuzz.token_sort_ratio(g.get("address", ""), c.get("address", ""))
        scores["address"].append(addr_sim)

        g_phones = set(g.get("phones", []))
        c_phones = set(c.get("phones", []))
        phone_sim = (len(g_phones & c_phones) / len(g_phones | c_phones) * 100.0) if (g_phones | c_phones) else 100.0
        scores["phones"].append(phone_sim)

        g_emails = set(g.get("emails", []))
        c_emails = set(c.get("emails", []))
        email_sim = (len(g_emails & c_emails) / len(g_emails | c_emails) * 100.0) if (g_emails | c_emails) else 100.0
        scores["emails"].append(email_sim)

        g_reps = [r.get("name", "").lower() for r in g.get("representatives", [])]
        c_reps = [r.get("name", "").lower() for r in c.get("representatives", [])]
        rep_sim = fuzz.token_sort_ratio(" ".join(g_reps), " ".join(c_reps))
        scores["representatives"].append(rep_sim)

        nb_sim = fuzz.token_sort_ratio(g.get("nature_of_business", ""), c.get("nature_of_business", ""))
        scores["nature_of_business"].append(nb_sim)

    print("\n=======================================================")
    print("      MSME EXTRACTION ACCURACY REPORT (GOLD SET)")
    print("=======================================================")
    print(f"Total Fixtures Evaluated: {total}\n")
    print(f"{'Field Name':<25} | {'Average Match Accuracy':<20}")
    print("-" * 52)

    for field, vals in scores.items():
        avg_score = sum(vals) / len(vals) if vals else 0.0
        print(f"{field:<25} | {avg_score:>6.2f}%")

    print("-" * 52)
    overall_avg = sum(sum(v) / len(v) for v in scores.values()) / len(scores)
    print(f"{'OVERALL PIPELINE SCORE':<25} | {overall_avg:>6.2f}%")
    print("=======================================================\n")


def main():
    if not os.path.exists(GOLD_SET_PATH):
        print(f"Error: {GOLD_SET_PATH} not found!")
        sys.exit(1)

    with open(GOLD_SET_PATH, "r", encoding="utf-8") as f:
        gold_records = json.load(f)

    cand_path = sys.argv[1] if len(sys.argv) > 1 else GOLD_SET_PATH
    with open(cand_path, "r", encoding="utf-8") as f:
        candidate_records = json.load(f)

    calculate_field_accuracy(gold_records, candidate_records)


if __name__ == "__main__":
    main()