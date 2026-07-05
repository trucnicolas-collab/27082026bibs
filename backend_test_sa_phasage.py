#!/usr/bin/env python3
"""
Backend test suite for VT/Phasage Carrefour app - SA Phasage + Step2-Validation testing.
Tests the new SA breakdown logic, sa-install config, and step2-validation fixes.
"""
import requests
import io
import os
from openpyxl import Workbook

# Backend URL from frontend/.env
BACKEND_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://go-lang-43.preview.emergentagent.com")
API_BASE = f"{BACKEND_URL}/api"

# Test credentials from /app/memory/test_credentials.md
ADMIN_EMAIL = "admin@vusion.local"
ADMIN_PASSWORD = "admin123"

# Global state
auth_cookies = None
upload_id = None


def login():
    """Login as admin and get JWT token."""
    global auth_cookies
    print("\n=== LOGIN ===")
    resp = requests.post(
        f"{API_BASE}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    data = resp.json()
    print(f"Logged in as: {data.get('email')}")
    auth_cookies = resp.cookies
    return auth_cookies


def create_sa_excel():
    """Create Excel with SA rows across >=2 sectors/rayons as specified in review request."""
    print("\n=== CREATING SA EXCEL ===")
    wb = Workbook()
    ws = wb.active
    
    # Header row - EXACT column names required
    headers = ["Secteur", "Rayon", "N° allée", "Type", "Référence", "Désignation", "Quantité"]
    ws.append(headers)
    
    # Add SA rows across multiple sectors/rayons as specified:
    # NAL/Conserves EEG ES 1.5 (noir) 1200; NAL/Liquides EEG ES 2.1 (blanc) 2000;
    # PGC/Épicerie EEG "SA 2.1 (noir)" 300; PGC/Frais EEG "SA 1.5 (noir)" 200;
    # PGC/Frozen EEG "SA 2.1 Freezer noir" 120; NAL/Bazar EEG "SA 1.5 (blanc)" 80.
    rows = [
        ["NAL", "Conserves", "1", "EEG", "15024", "ES 1.5 (noir)", 1200],
        ["NAL", "Liquides", "2", "EEG", "17740", "ES 2.1 (blanc)", 2000],
        ["PGC", "Épicerie", "3", "EEG", "15910", "SA 2.1 (noir)", 300],
        ["PGC", "Frais", "4", "EEG", "15551", "SA 1.5 (noir)", 200],
        ["PGC", "Frozen", "5", "EEG", "15552", "SA 2.1 Freezer noir", 120],
        ["NAL", "Bazar", "6", "EEG", "15553", "SA 1.5 (blanc)", 80],
    ]
    for row in rows:
        ws.append(row)
    
    # Save to bytes
    excel_bytes = io.BytesIO()
    wb.save(excel_bytes)
    excel_bytes.seek(0)
    print(f"Created Excel with {len(rows)} SA data rows across multiple sectors/rayons")
    return excel_bytes


def upload_excel(cookies):
    """Upload synthetic Excel and get upload_id."""
    global upload_id
    print("\n=== UPLOADING EXCEL ===")
    
    excel_bytes = create_sa_excel()
    files = {"file": ("test_sa_inventory.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    
    resp = requests.post(
        f"{API_BASE}/upload-excel",
        files=files,
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    
    data = resp.json()
    upload_id = data.get("upload_id")
    print(f"Upload ID: {upload_id}")
    assert upload_id, "No upload_id in response"
    return upload_id


def test_phasage_summary_sa_breakdown(cookies, upload_id):
    """Test 1-4: Verify SA breakdown logic in phasage-summary."""
    print("\n=== TEST 1-4: PHASAGE SUMMARY SA BREAKDOWN ===")
    
    resp = requests.get(
        f"{API_BASE}/dataset/{upload_id}/phasage-summary",
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to get phasage-summary: {resp.text}"
    
    data = resp.json()
    # The endpoint returns the summary directly, not wrapped in a "summary" key
    totals = data.get("totals", {})
    sa_breakdown = data.get("sa_breakdown", [])
    allees = data.get("allees", [])
    sa_install = data.get("sa_install", {})
    
    print(f"\n--- Totals ---")
    print(f"sa_15: {totals.get('sa_15')}")
    print(f"sa_21: {totals.get('sa_21')}")
    print(f"sa_21_std: {totals.get('sa_21_std')}")
    print(f"sa_21_freezer: {totals.get('sa_21_freezer')}")
    
    # TEST 1: Verify totals has sa_15, sa_21, sa_21_freezer, sa_21_std
    # Expected: sa_15 = 200 + 80 = 280, sa_21_freezer = 120, sa_21_std = 300, sa_21 = 300 + 120 = 420
    assert "sa_15" in totals, "Missing sa_15 in totals"
    assert "sa_21" in totals, "Missing sa_21 in totals"
    assert "sa_21_freezer" in totals, "Missing sa_21_freezer in totals"
    assert "sa_21_std" in totals, "Missing sa_21_std in totals"
    
    sa_15 = totals["sa_15"]
    sa_21 = totals["sa_21"]
    sa_21_freezer = totals["sa_21_freezer"]
    sa_21_std = totals["sa_21_std"]
    
    # Verify coherence: sa_21 == sa_21_std + sa_21_freezer
    assert sa_21 == sa_21_std + sa_21_freezer, f"Incoherent: sa_21 ({sa_21}) != sa_21_std ({sa_21_std}) + sa_21_freezer ({sa_21_freezer})"
    
    # Verify expected values based on uploaded data
    assert sa_21_freezer == 120, f"Expected sa_21_freezer=120, got {sa_21_freezer}"
    assert sa_21_std == 300, f"Expected sa_21_std=300, got {sa_21_std}"
    assert sa_15 == 280, f"Expected sa_15=280 (200+80), got {sa_15}"
    assert sa_21 == 420, f"Expected sa_21=420 (300+120), got {sa_21}"
    
    print("✅ TEST 1 PASS: totals has correct sa_15, sa_21, sa_21_std, sa_21_freezer with coherence")
    
    # TEST 2: Verify sa_breakdown structure
    print(f"\n--- SA Breakdown ---")
    print(f"Number of sectors: {len(sa_breakdown)}")
    
    assert isinstance(sa_breakdown, list), "sa_breakdown should be a list"
    assert len(sa_breakdown) > 0, "sa_breakdown should not be empty"
    
    total_sa_15_sectors = 0
    total_sa_21_std_sectors = 0
    total_sa_21_freezer_sectors = 0
    
    for sector in sa_breakdown:
        print(f"\nSector: {sector.get('secteur')}")
        print(f"  sa_15: {sector.get('sa_15')}, sa_21_std: {sector.get('sa_21_std')}, sa_21_freezer: {sector.get('sa_21_freezer')}")
        
        # Verify structure
        assert "secteur" in sector, "Missing 'secteur' in sa_breakdown item"
        assert "sa_15" in sector, "Missing 'sa_15' in sa_breakdown item"
        assert "sa_21_std" in sector, "Missing 'sa_21_std' in sa_breakdown item"
        assert "sa_21_freezer" in sector, "Missing 'sa_21_freezer' in sa_breakdown item"
        assert "rayons" in sector, "Missing 'rayons' in sa_breakdown item"
        assert isinstance(sector["rayons"], list), "rayons should be a list"
        
        # Verify sum of rayons == sector totals
        sector_sa_15 = sector["sa_15"]
        sector_sa_21_std = sector["sa_21_std"]
        sector_sa_21_freezer = sector["sa_21_freezer"]
        
        rayons_sa_15 = sum(r.get("sa_15", 0) for r in sector["rayons"])
        rayons_sa_21_std = sum(r.get("sa_21_std", 0) for r in sector["rayons"])
        rayons_sa_21_freezer = sum(r.get("sa_21_freezer", 0) for r in sector["rayons"])
        
        assert rayons_sa_15 == sector_sa_15, f"Sector {sector['secteur']}: rayons sa_15 sum ({rayons_sa_15}) != sector sa_15 ({sector_sa_15})"
        assert rayons_sa_21_std == sector_sa_21_std, f"Sector {sector['secteur']}: rayons sa_21_std sum ({rayons_sa_21_std}) != sector sa_21_std ({sector_sa_21_std})"
        assert rayons_sa_21_freezer == sector_sa_21_freezer, f"Sector {sector['secteur']}: rayons sa_21_freezer sum ({rayons_sa_21_freezer}) != sector sa_21_freezer ({sector_sa_21_freezer})"
        
        # Print rayons
        for rayon in sector["rayons"]:
            print(f"    Rayon: {rayon.get('rayon')}, sa_15: {rayon.get('sa_15')}, sa_21_std: {rayon.get('sa_21_std')}, sa_21_freezer: {rayon.get('sa_21_freezer')}")
            assert "rayon" in rayon, "Missing 'rayon' in rayon item"
            assert "sa_15" in rayon, "Missing 'sa_15' in rayon item"
            assert "sa_21_std" in rayon, "Missing 'sa_21_std' in rayon item"
            assert "sa_21_freezer" in rayon, "Missing 'sa_21_freezer' in rayon item"
        
        total_sa_15_sectors += sector_sa_15
        total_sa_21_std_sectors += sector_sa_21_std
        total_sa_21_freezer_sectors += sector_sa_21_freezer
    
    # Verify sum of sectors == totals
    assert total_sa_15_sectors == sa_15, f"Sum of sectors sa_15 ({total_sa_15_sectors}) != totals sa_15 ({sa_15})"
    assert total_sa_21_std_sectors == sa_21_std, f"Sum of sectors sa_21_std ({total_sa_21_std_sectors}) != totals sa_21_std ({sa_21_std})"
    assert total_sa_21_freezer_sectors == sa_21_freezer, f"Sum of sectors sa_21_freezer ({total_sa_21_freezer_sectors}) != totals sa_21_freezer ({sa_21_freezer})"
    
    print("✅ TEST 2 PASS: sa_breakdown structure correct, sum of rayons == sector totals, sum of sectors == totals")
    
    # TEST 3: Verify allees[] contains sa_21_freezer and sa_21_std
    print(f"\n--- Allees ---")
    print(f"Number of allees: {len(allees)}")
    
    assert len(allees) > 0, "allees should not be empty"
    
    for allee in allees:
        if allee.get("sa_21", 0) > 0:  # Only check allees with SA 2.1
            print(f"Allee {allee.get('allee')}: sa_21={allee.get('sa_21')}, sa_21_std={allee.get('sa_21_std')}, sa_21_freezer={allee.get('sa_21_freezer')}")
            assert "sa_21_freezer" in allee, f"Missing sa_21_freezer in allee {allee.get('allee')}"
            assert "sa_21_std" in allee, f"Missing sa_21_std in allee {allee.get('allee')}"
    
    print("✅ TEST 3 PASS: allees[] contains sa_21_freezer and sa_21_std")
    
    # TEST 4: Verify sa_install present with default enabled:false
    print(f"\n--- SA Install ---")
    print(f"sa_install: {sa_install}")
    
    assert isinstance(sa_install, dict), "sa_install should be a dict"
    assert "enabled" in sa_install, "Missing 'enabled' in sa_install"
    assert sa_install["enabled"] == False, f"Expected sa_install.enabled=False by default, got {sa_install['enabled']}"
    
    print("✅ TEST 4 PASS: sa_install present with default enabled=False")
    
    return data


def test_sa_install_config(cookies, upload_id):
    """Test 5: PATCH sa-install config and verify persistence."""
    print("\n=== TEST 5: SA-INSTALL CONFIG & PERSISTENCE ===")
    
    # PATCH sa-install with specific config
    config = {
        "enabled": True,
        "sa_21": True,
        "freezer": True,
        "selection": {
            "sa_21": ["PGC|||Épicerie"]
        }
    }
    
    print(f"PATCH /sa-install with config: {config}")
    resp = requests.patch(
        f"{API_BASE}/dataset/{upload_id}/sa-install",
        json=config,
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to PATCH sa-install: {resp.text}"
    
    data = resp.json()
    sa_install_response = data.get("sa_install", {})
    print(f"Response sa_install: {sa_install_response}")
    
    assert sa_install_response.get("enabled") == True, "sa_install.enabled should be True"
    assert sa_install_response.get("sa_21") == True, "sa_install.sa_21 should be True"
    assert sa_install_response.get("freezer") == True, "sa_install.freezer should be True"
    assert "selection" in sa_install_response, "Missing 'selection' in sa_install"
    
    print("✅ PATCH sa-install successful")
    
    # Verify persistence by calling GET phasage-summary multiple times (2-3 times)
    print("\n--- Testing persistence (calling GET phasage-summary 3 times) ---")
    
    for i in range(1, 4):
        print(f"\nGET #{i}")
        resp = requests.get(
            f"{API_BASE}/dataset/{upload_id}/phasage-summary",
            cookies=cookies,
            timeout=30
        )
        assert resp.status_code == 200, f"Failed to get phasage-summary on attempt {i}: {resp.text}"
        
        data = resp.json()
        sa_install = data.get("sa_install", {})
        
        print(f"  sa_install.enabled: {sa_install.get('enabled')}")
        print(f"  sa_install.sa_21: {sa_install.get('sa_21')}")
        print(f"  sa_install.freezer: {sa_install.get('freezer')}")
        print(f"  sa_install.selection: {sa_install.get('selection')}")
        
        # Verify values persisted
        assert sa_install.get("enabled") == True, f"Attempt {i}: sa_install.enabled should be True (persistence failed)"
        assert sa_install.get("sa_21") == True, f"Attempt {i}: sa_install.sa_21 should be True (persistence failed)"
        assert sa_install.get("freezer") == True, f"Attempt {i}: sa_install.freezer should be True (persistence failed)"
        assert sa_install.get("selection", {}).get("sa_21") == ["PGC|||Épicerie"], f"Attempt {i}: sa_install.selection.sa_21 should be ['PGC|||Épicerie'] (persistence failed)"
    
    print("✅ TEST 5 PASS: sa-install config persisted correctly across multiple GET requests")


def test_step2_validation_initial(cookies, upload_id):
    """Test 6: step2-validation on fresh dataset (no surface, no dongles)."""
    print("\n=== TEST 6: STEP2-VALIDATION INITIAL (no surface, no dongles) ===")
    
    resp = requests.get(
        f"{API_BASE}/dataset/{upload_id}/step2-validation",
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to get step2-validation: {resp.text}"
    
    data = resp.json()
    print(f"Response: {data}")
    
    ok = data.get("ok")
    issues = data.get("issues", [])
    
    print(f"ok: {ok}")
    print(f"issues: {issues}")
    
    # Should be ok=False with surface_missing and dongles_missing
    assert ok == False, "Expected ok=False when surface and dongles are missing"
    
    issue_codes = [issue.get("code") for issue in issues]
    print(f"Issue codes: {issue_codes}")
    
    assert "surface_missing" in issue_codes, "Expected 'surface_missing' in issues"
    assert "dongles_missing" in issue_codes, "Expected 'dongles_missing' in issues"
    
    print("✅ TEST 6 PASS: step2-validation correctly reports surface_missing and dongles_missing")


def test_step2_validation_dongles_fix(cookies, upload_id):
    """Test 7: PATCH dongles, then verify step2-validation reflects immediately (cache fix)."""
    print("\n=== TEST 7: STEP2-VALIDATION DONGLES CACHE FIX ===")
    
    # PATCH dongles
    print("PATCH /dongles with quantity=10")
    resp = requests.patch(
        f"{API_BASE}/dataset/{upload_id}/dongles",
        json={"quantity": 10},
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to PATCH dongles: {resp.text}"
    
    # Immediately GET step2-validation
    print("\nImmediately GET /step2-validation")
    resp = requests.get(
        f"{API_BASE}/dataset/{upload_id}/step2-validation",
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to get step2-validation: {resp.text}"
    
    data = resp.json()
    print(f"Response: {data}")
    
    ok = data.get("ok")
    issues = data.get("issues", [])
    dongles_quantity = data.get("dongles_quantity")
    
    print(f"ok: {ok}")
    print(f"dongles_quantity: {dongles_quantity}")
    print(f"issues: {issues}")
    
    # Verify dongles_missing is NO LONGER present
    issue_codes = [issue.get("code") for issue in issues]
    print(f"Issue codes: {issue_codes}")
    
    assert "dongles_missing" not in issue_codes, "Expected 'dongles_missing' to be gone after PATCH dongles"
    assert dongles_quantity == 10, f"Expected dongles_quantity=10, got {dongles_quantity}"
    
    print("✅ TEST 7 PASS: dongles_missing disappeared immediately after PATCH (cache fix working)")


def test_step2_validation_surface_fix(cookies, upload_id):
    """Test 8: PATCH surface, verify surface_missing gone, system rows don't trigger unprocessed_refs."""
    print("\n=== TEST 8: STEP2-VALIDATION SURFACE FIX + SYSTEM ROWS ===")
    
    # PATCH surface
    print("PATCH /surface with category=plus_10000")
    resp = requests.patch(
        f"{API_BASE}/dataset/{upload_id}/surface",
        json={"category": "plus_10000"},
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to PATCH surface: {resp.text}"
    
    # GET step2-validation
    print("\nGET /step2-validation")
    resp = requests.get(
        f"{API_BASE}/dataset/{upload_id}/step2-validation",
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to get step2-validation: {resp.text}"
    
    data = resp.json()
    print(f"Response: {data}")
    
    ok = data.get("ok")
    issues = data.get("issues", [])
    surface_category = data.get("surface_category")
    
    print(f"ok: {ok}")
    print(f"surface_category: {surface_category}")
    print(f"issues: {issues}")
    
    # Verify surface_missing is gone
    issue_codes = [issue.get("code") for issue in issues]
    print(f"Issue codes: {issue_codes}")
    
    assert "surface_missing" not in issue_codes, "Expected 'surface_missing' to be gone after PATCH surface"
    assert surface_category == "plus_10000", f"Expected surface_category=plus_10000, got {surface_category}"
    
    # CRITICAL: The auto-generated "Support individuel alu SA" line (kind surface_added, empty reference)
    # must NOT trigger "unprocessed_refs" (system rows are excluded)
    # After surface+dongles set (and no user rows with bad refs), ok should be TRUE
    assert ok == True, f"Expected ok=True after surface+dongles set (no bad user refs), but got ok={ok}. Issues: {issues}"
    assert "unprocessed_refs" not in issue_codes, "System row 'Support individuel alu SA' should NOT trigger unprocessed_refs"
    
    print("✅ TEST 8 PASS: surface_missing gone, system rows do NOT trigger unprocessed_refs, ok=True")


def test_step2_validation_bad_refs(cookies, upload_id):
    """Test 9: Add manual row with bad ref, verify unprocessed_refs appears, then fix it."""
    print("\n=== TEST 9: STEP2-VALIDATION BAD REFS ===")
    
    # Add a new recap row via POST (adds empty row)
    print("\nPOST /recap-row to add a manual row")
    resp = requests.post(
        f"{API_BASE}/dataset/{upload_id}/recap-row",
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to POST recap-row: {resp.text}"
    
    data = resp.json()
    new_index = data.get("index")
    print(f"Added row at index {new_index}")
    assert new_index is not None, "No index returned from POST recap-row"
    
    # PATCH the row to add a designation and non-numeric reference
    print(f"\nPATCH /recap-row/{new_index} to set designation and reference=AUTRE1 (non-numeric)")
    resp = requests.patch(
        f"{API_BASE}/dataset/{upload_id}/recap-row/{new_index}",
        json={"designation": "Test Manual Row", "reference": "AUTRE1"},
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to PATCH recap-row: {resp.text}"
    
    # GET step2-validation - should show unprocessed_refs
    print("\nGET /step2-validation (should show unprocessed_refs)")
    resp = requests.get(
        f"{API_BASE}/dataset/{upload_id}/step2-validation",
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to get step2-validation: {resp.text}"
    
    data = resp.json()
    print(f"Response: {data}")
    
    ok = data.get("ok")
    issues = data.get("issues", [])
    
    print(f"ok: {ok}")
    print(f"issues: {issues}")
    
    issue_codes = [issue.get("code") for issue in issues]
    print(f"Issue codes: {issue_codes}")
    
    assert ok == False, "Expected ok=False when there's a bad reference"
    assert "unprocessed_refs" in issue_codes, "Expected 'unprocessed_refs' in issues after setting bad reference"
    
    print("✅ unprocessed_refs appeared as expected")
    
    # Fix the reference back to numeric
    print(f"\nPATCH /recap-row/{new_index} to set reference=88888 (numeric)")
    resp = requests.patch(
        f"{API_BASE}/dataset/{upload_id}/recap-row/{new_index}",
        json={"reference": "88888"},
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to PATCH recap-row: {resp.text}"
    
    # GET step2-validation - unprocessed_refs should be gone
    print("\nGET /step2-validation (unprocessed_refs should be gone)")
    resp = requests.get(
        f"{API_BASE}/dataset/{upload_id}/step2-validation",
        cookies=cookies,
        timeout=30
    )
    print(f"Status: {resp.status_code}")
    assert resp.status_code == 200, f"Failed to get step2-validation: {resp.text}"
    
    data = resp.json()
    print(f"Response: {data}")
    
    ok = data.get("ok")
    issues = data.get("issues", [])
    
    print(f"ok: {ok}")
    print(f"issues: {issues}")
    
    issue_codes = [issue.get("code") for issue in issues]
    print(f"Issue codes: {issue_codes}")
    
    assert ok == True, f"Expected ok=True after fixing reference, but got ok={ok}. Issues: {issues}"
    assert "unprocessed_refs" not in issue_codes, "Expected 'unprocessed_refs' to be gone after fixing reference"
    
    print("✅ TEST 9 PASS: unprocessed_refs appeared with bad ref, disappeared after fixing")


def test_regression_totals_stability(cookies, upload_id):
    """Regression test: GET phasage-summary repeatedly and confirm totals are identical."""
    print("\n=== REGRESSION TEST: TOTALS STABILITY ===")
    
    print("Calling GET /phasage-summary 5 times to verify totals stability...")
    
    totals_list = []
    
    for i in range(1, 6):
        print(f"\nGET #{i}")
        resp = requests.get(
            f"{API_BASE}/dataset/{upload_id}/phasage-summary",
            cookies=cookies,
            timeout=30
        )
        assert resp.status_code == 200, f"Failed to get phasage-summary on attempt {i}: {resp.text}"
        
        data = resp.json()
        totals = data.get("totals", {})
        
        # Extract key totals
        key_totals = {
            "es_15": totals.get("es_15"),
            "es_21": totals.get("es_21"),
            "sa_15": totals.get("sa_15"),
            "sa_21": totals.get("sa_21"),
            "sa_21_std": totals.get("sa_21_std"),
            "sa_21_freezer": totals.get("sa_21_freezer"),
        }
        
        print(f"  Totals: {key_totals}")
        totals_list.append(key_totals)
    
    # Verify all totals are identical
    first_totals = totals_list[0]
    for i, totals in enumerate(totals_list[1:], start=2):
        assert totals == first_totals, f"Totals drift detected on attempt {i}: {totals} != {first_totals}"
    
    print("\n✅ REGRESSION TEST PASS: Totals are IDENTICAL across all 5 fetches (no drift)")


def main():
    """Run all SA phasage + step2-validation tests."""
    print("=" * 80)
    print("SA PHASAGE + STEP2-VALIDATION BACKEND TESTS")
    print("=" * 80)
    
    try:
        # Login
        cookies = login()
        
        # Upload Excel with SA data
        upload_id = upload_excel(cookies)
        
        # Test 1-4: Phasage summary SA breakdown
        test_phasage_summary_sa_breakdown(cookies, upload_id)
        
        # Test 5: SA-install config and persistence
        test_sa_install_config(cookies, upload_id)
        
        # Test 6: step2-validation initial (no surface, no dongles)
        test_step2_validation_initial(cookies, upload_id)
        
        # Test 7: step2-validation dongles cache fix
        test_step2_validation_dongles_fix(cookies, upload_id)
        
        # Test 8: step2-validation surface fix + system rows
        test_step2_validation_surface_fix(cookies, upload_id)
        
        # Test 9: step2-validation bad refs
        test_step2_validation_bad_refs(cookies, upload_id)
        
        # Regression: totals stability
        test_regression_totals_stability(cookies, upload_id)
        
        print("\n" + "=" * 80)
        print("✅✅✅ ALL TESTS PASSED ✅✅✅")
        print("=" * 80)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise


if __name__ == "__main__":
    main()
