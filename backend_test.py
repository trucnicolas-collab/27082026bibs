#!/usr/bin/env python3
"""
Backend test suite for VT/Phasage Carrefour app.
Tests the 5 critical requirements from the review request.
"""
import requests
import openpyxl
from openpyxl import Workbook
import io
import json
import sys

# Backend URL from frontend/.env
BASE_URL = "https://go-lang-43.preview.emergentagent.com/api"

# Admin credentials from test_credentials.md
ADMIN_EMAIL = "admin@vusion.local"
ADMIN_PASSWORD = "admin123"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def log_pass(msg):
    print(f"{Colors.GREEN}✓ PASS{Colors.RESET}: {msg}")

def log_fail(msg):
    print(f"{Colors.RED}✗ FAIL{Colors.RESET}: {msg}")

def log_info(msg):
    print(f"{Colors.BLUE}ℹ INFO{Colors.RESET}: {msg}")

def log_step(msg):
    print(f"\n{Colors.YELLOW}═══ {msg} ═══{Colors.RESET}")

def create_synthetic_excel():
    """Create a synthetic Excel file with required columns and EEG data."""
    wb = Workbook()
    ws = wb.active
    
    # Header row - EXACTLY these columns are required
    headers = ["Secteur", "Rayon", "N° allée", "Type", "Référence", "Désignation", "Quantité"]
    ws.append(headers)
    
    # Data rows with EEG items to generate non-zero phasage summary
    data_rows = [
        # EEG rows for phasage summary
        ["Frais", "Fruits", 1, "EEG", "15024", "ES 1.5 (noir)", 1000],
        ["Frais", "Fruits", 1, "EEG", "17869", "ES 2.1 (blanc)", 800],
        ["Frais", "Légumes", 2, "EEG", "15910", "SA 2.1 (noir)", 2000],
        ["Frais", "Légumes", 2, "EEG", "15024", "ES 1.5 (noir)", 500],
        ["Épicerie", "Conserves", 3, "EEG", "15910", "SA 2.1 (noir)", 1500],
        ["Épicerie", "Conserves", 3, "EEG", "15912", "SA 1.5 (noir)", 300],
        ["Épicerie", "Pâtes", 4, "EEG", "17869", "ES 2.1 (blanc)", 600],
        ["Épicerie", "Pâtes", 4, "EEG", "15024", "ES 1.5 (noir)", 400],
        # Rail rows
        ["Frais", "Fruits", 1, "Rail", "16957", "Rail 1187mm", 50],
        ["Frais", "Légumes", 2, "Rail", "14745", "Rail 1320mm", 60],
        ["Épicerie", "Conserves", 3, "Rail", "15507", "Rail 1240mm", 40],
        # Additional EEG rows for variety
        ["Boissons", "Eaux", 5, "EEG", "15024", "ES 1.5 (noir)", 700],
        ["Boissons", "Sodas", 6, "EEG", "15910", "SA 2.1 (noir)", 1200],
        ["Hygiène", "Savons", 7, "EEG", "17869", "ES 2.1 (blanc)", 500],
        ["Hygiène", "Shampoings", 8, "EEG", "15912", "SA 1.5 (noir)", 250],
    ]
    
    for row in data_rows:
        ws.append(row)
    
    # Save to BytesIO
    excel_buffer = io.BytesIO()
    wb.save(excel_buffer)
    excel_buffer.seek(0)
    return excel_buffer

def test_step_1_upload_excel(session):
    """STEP 1: Upload synthetic Excel and verify upload_id is returned."""
    log_step("STEP 1: Upload Synthetic Excel")
    
    excel_file = create_synthetic_excel()
    files = {'file': ('test_data.xlsx', excel_file, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
    
    response = session.post(f"{BASE_URL}/upload-excel", files=files)
    
    if response.status_code != 200:
        log_fail(f"Upload failed with status {response.status_code}: {response.text}")
        return None
    
    data = response.json()
    upload_id = data.get("upload_id")
    
    if not upload_id:
        log_fail("No upload_id in response")
        return None
    
    log_pass(f"Excel uploaded successfully, upload_id: {upload_id}")
    log_info(f"Row count: {data.get('row_count')}")
    return upload_id

def test_step_2_anti_cache_headers(session, upload_id):
    """STEP 2: Verify anti-cache headers on GET /api/ and GET /api/dataset/{id}/phasage-summary."""
    log_step("STEP 2: Anti-Cache Headers (Cache-Control: no-store)")
    
    all_passed = True
    
    # Test GET /api/
    log_info("Testing GET /api/")
    response = session.get(f"{BASE_URL}/")
    cache_control = response.headers.get("Cache-Control", "")
    
    if "no-store" in cache_control:
        log_pass(f"GET /api/ has Cache-Control: {cache_control}")
    else:
        log_fail(f"GET /api/ missing 'no-store' in Cache-Control: {cache_control}")
        all_passed = False
    
    # Test GET /api/dataset/{id}/phasage-summary
    log_info(f"Testing GET /api/dataset/{upload_id}/phasage-summary")
    response = session.get(f"{BASE_URL}/dataset/{upload_id}/phasage-summary")
    
    if response.status_code != 200:
        log_fail(f"Phasage-summary request failed: {response.status_code}")
        return False
    
    cache_control = response.headers.get("Cache-Control", "")
    
    if "no-store" in cache_control:
        log_pass(f"GET /api/dataset/{{id}}/phasage-summary has Cache-Control: {cache_control}")
    else:
        log_fail(f"GET /api/dataset/{{id}}/phasage-summary missing 'no-store': {cache_control}")
        all_passed = False
    
    return all_passed

def test_step_3_determinism(session, upload_id):
    """STEP 3: Verify determinism of Total EEG across multiple calls with interleaved operations."""
    log_step("STEP 3: Determinism of Total EEG")
    
    # Initial phasage-summary call
    log_info("Fetching initial phasage-summary...")
    response = session.get(f"{BASE_URL}/dataset/{upload_id}/phasage-summary")
    if response.status_code != 200:
        log_fail(f"Initial phasage-summary failed: {response.status_code}")
        return False
    
    initial_summary = response.json()
    initial_totals = initial_summary.get("totals", {})
    
    log_info(f"Initial totals: {json.dumps(initial_totals, indent=2)}")
    
    # Store the baseline totals (these should NEVER change)
    baseline = {
        "es_15": initial_totals.get("es_15"),
        "es_21": initial_totals.get("es_21"),
        "sa_15": initial_totals.get("sa_15"),
        "sa_21": initial_totals.get("sa_21"),
        "fleches": initial_totals.get("fleches"),
        "rails_es": initial_totals.get("rails_es"),
    }
    
    all_passed = True
    
    # Interleaved operations
    operations = [
        ("GET /dataset/{id}", lambda: session.get(f"{BASE_URL}/dataset/{upload_id}")),
        ("PATCH /dongles", lambda: session.patch(f"{BASE_URL}/dataset/{upload_id}/dongles", json={"quantity": 20})),
        ("GET /dataset/{id}", lambda: session.get(f"{BASE_URL}/dataset/{upload_id}")),
    ]
    
    for i, (op_name, op_func) in enumerate(operations, 1):
        log_info(f"Operation {i}: {op_name}")
        op_response = op_func()
        
        if op_response.status_code not in [200, 201]:
            log_fail(f"{op_name} failed with status {op_response.status_code}")
            all_passed = False
            continue
        
        # Re-fetch phasage-summary after each operation
        log_info(f"Re-fetching phasage-summary after {op_name}...")
        response = session.get(f"{BASE_URL}/dataset/{upload_id}/phasage-summary")
        
        if response.status_code != 200:
            log_fail(f"Phasage-summary fetch failed after {op_name}")
            all_passed = False
            continue
        
        current_summary = response.json()
        current_totals = current_summary.get("totals", {})
        
        # Verify each baseline total hasn't changed
        for key, expected_value in baseline.items():
            actual_value = current_totals.get(key)
            if actual_value != expected_value:
                log_fail(f"DRIFT DETECTED in {key} after {op_name}: expected {expected_value}, got {actual_value}")
                all_passed = False
            else:
                log_pass(f"{key} remains stable: {actual_value}")
    
    # Final verification: fetch phasage-summary 2 more times
    for i in range(2):
        log_info(f"Final verification fetch #{i+1}...")
        response = session.get(f"{BASE_URL}/dataset/{upload_id}/phasage-summary")
        
        if response.status_code != 200:
            log_fail(f"Final fetch #{i+1} failed")
            all_passed = False
            continue
        
        current_summary = response.json()
        current_totals = current_summary.get("totals", {})
        
        for key, expected_value in baseline.items():
            actual_value = current_totals.get(key)
            if actual_value != expected_value:
                log_fail(f"DRIFT in {key} on final fetch #{i+1}: expected {expected_value}, got {actual_value}")
                all_passed = False
    
    if all_passed:
        log_pass("All totals remained stable across all operations - NO DRIFT detected")
    
    return all_passed

def test_step_4_moq_refs(session, upload_id):
    """STEP 4: Verify MOQ=100 for refs 13469 and 17740."""
    log_step("STEP 4: MOQ=100 for refs 13469 and 17740")
    
    all_passed = True
    
    # Test ref 13469 - Add a new row
    log_info("Adding new recap row for ref 13469...")
    response = session.post(f"{BASE_URL}/dataset/{upload_id}/recap-row")
    if response.status_code != 200:
        log_fail(f"Failed to add recap row: {response.status_code}")
        return False
    
    new_row_data = response.json()
    target_index = new_row_data.get("index")
    
    log_info(f"Testing ref 13469 with MOQ=100 at index {target_index}")
    payload = {
        "type": "EEG",
        "reference": "13469",
        "designation": "Test Product 13469",
        "quantite": 150,  # Should round up to 200
        "spare": ""  # Let backend auto-calculate
    }
    
    response = session.patch(f"{BASE_URL}/dataset/{upload_id}/recap-row/{target_index}", json=payload)
    if response.status_code != 200:
        log_fail(f"Failed to update recap row: {response.status_code}")
        return False
    
    # Get dataset again to verify total_moq
    # Note: The index may have changed due to sectioning, so find by reference
    response = session.get(f"{BASE_URL}/dataset/{upload_id}")
    if response.status_code != 200:
        log_fail(f"Failed to get dataset after update: {response.status_code}")
        return False
    
    data = response.json()
    recap_rows = data.get("data", {}).get("recap", [])
    
    # Find the row with ref 13469
    updated_row = None
    for row in recap_rows:
        if row.get("reference") == "13469":
            updated_row = row
            break
    
    if not updated_row:
        log_fail("Could not find row with ref 13469 after update")
        return False
    
    total_moq = updated_row.get("total_moq")
    total_plus_spare = updated_row.get("total_plus_spare")
    
    log_info(f"Ref 13469: total_plus_spare={total_plus_spare}, total_moq={total_moq}")
    
    # total_plus_spare = 150 + auto-spare (8) = 158, should round up to 200
    if total_moq == 200:
        log_pass(f"Ref 13469: total_moq correctly rounded to 200 (from {total_plus_spare})")
    else:
        log_fail(f"Ref 13469: total_moq should be 200, got {total_moq}")
        all_passed = False
    
    # Test ref 17740 - Add another new row
    log_info("Adding new recap row for ref 17740...")
    response = session.post(f"{BASE_URL}/dataset/{upload_id}/recap-row")
    if response.status_code != 200:
        log_fail(f"Failed to add recap row: {response.status_code}")
        return False
    
    new_row_data = response.json()
    target_index = new_row_data.get("index")
    
    log_info(f"Testing ref 17740 with MOQ=100 at index {target_index}")
    payload = {
        "type": "EEG",
        "reference": "17740",
        "designation": "Test Product 17740",
        "quantite": 250,  # Should round up to 300
        "spare": ""  # Let backend auto-calculate
    }
    
    response = session.patch(f"{BASE_URL}/dataset/{upload_id}/recap-row/{target_index}", json=payload)
    if response.status_code != 200:
        log_fail(f"Failed to update recap row: {response.status_code}")
        return False
    
    # Get dataset again and find by reference
    response = session.get(f"{BASE_URL}/dataset/{upload_id}")
    if response.status_code != 200:
        log_fail(f"Failed to get dataset after update: {response.status_code}")
        return False
    
    data = response.json()
    recap_rows = data.get("data", {}).get("recap", [])
    
    # Find the row with ref 17740
    updated_row = None
    for row in recap_rows:
        if row.get("reference") == "17740":
            updated_row = row
            break
    
    if not updated_row:
        log_fail("Could not find row with ref 17740 after update")
        return False
    
    total_moq = updated_row.get("total_moq")
    total_plus_spare = updated_row.get("total_plus_spare")
    
    log_info(f"Ref 17740: total_plus_spare={total_plus_spare}, total_moq={total_moq}")
    
    # total_plus_spare = 250 + auto-spare (13) = 263, should round up to 300
    if total_moq == 300:
        log_pass(f"Ref 17740: total_moq correctly rounded to 300 (from {total_plus_spare})")
    else:
        log_fail(f"Ref 17740: total_moq should be 300, got {total_moq}")
        all_passed = False
    
    return all_passed

def test_step_5_saisonnier_support(session, upload_id):
    """STEP 5: Verify Saisonnier for 'Support individuel alu SA' based on surface category."""
    log_step("STEP 5: Saisonnier for 'Support individuel alu SA'")
    
    # First, add a recap row with "Support individuel alu SA"
    log_info("Adding recap row with 'Support individuel alu SA'...")
    response = session.post(f"{BASE_URL}/dataset/{upload_id}/recap-row")
    if response.status_code != 200:
        log_fail(f"Failed to add recap row: {response.status_code}")
        return False
    
    new_row_data = response.json()
    new_index = new_row_data.get("index")
    
    # Update the new row with Support individuel alu SA
    payload = {
        "designation": "Support individuel alu SA",
        "quantite": 50,
        "spare": 3
    }
    
    response = session.patch(f"{BASE_URL}/dataset/{upload_id}/recap-row/{new_index}", json=payload)
    if response.status_code != 200:
        log_fail(f"Failed to update recap row: {response.status_code}")
        return False
    
    all_passed = True
    
    # Test 1: Set surface to plus_10000 -> saisonnier should be 6000
    log_info("Setting surface category to plus_10000...")
    response = session.patch(f"{BASE_URL}/dataset/{upload_id}/surface", json={"category": "plus_10000"})
    if response.status_code != 200:
        log_fail(f"Failed to set surface category: {response.status_code}")
        return False
    
    # Get dataset to verify saisonnier
    response = session.get(f"{BASE_URL}/dataset/{upload_id}")
    if response.status_code != 200:
        log_fail(f"Failed to get dataset: {response.status_code}")
        return False
    
    data = response.json()
    recap_rows = data.get("data", {}).get("recap", [])
    
    # Find the Support individuel alu SA row
    support_row = None
    for row in recap_rows:
        if "support individuel alu sa" in (row.get("designation") or "").lower():
            support_row = row
            break
    
    if not support_row:
        log_fail("Could not find 'Support individuel alu SA' row")
        return False
    
    saisonnier = support_row.get("saisonnier")
    log_info(f"Surface=plus_10000: saisonnier={saisonnier}")
    
    if saisonnier == 6000:
        log_pass("Surface plus_10000: saisonnier correctly set to 6000")
    else:
        log_fail(f"Surface plus_10000: saisonnier should be 6000, got {saisonnier}")
        all_passed = False
    
    # Test 2: Set surface to moins_10000 -> saisonnier should be 4000
    log_info("Setting surface category to moins_10000...")
    response = session.patch(f"{BASE_URL}/dataset/{upload_id}/surface", json={"category": "moins_10000"})
    if response.status_code != 200:
        log_fail(f"Failed to set surface category: {response.status_code}")
        return False
    
    response = session.get(f"{BASE_URL}/dataset/{upload_id}")
    if response.status_code != 200:
        log_fail(f"Failed to get dataset: {response.status_code}")
        return False
    
    data = response.json()
    recap_rows = data.get("data", {}).get("recap", [])
    
    support_row = None
    for row in recap_rows:
        if "support individuel alu sa" in (row.get("designation") or "").lower():
            support_row = row
            break
    
    if not support_row:
        log_fail("Could not find 'Support individuel alu SA' row")
        return False
    
    saisonnier = support_row.get("saisonnier")
    log_info(f"Surface=moins_10000: saisonnier={saisonnier}")
    
    if saisonnier == 4000:
        log_pass("Surface moins_10000: saisonnier correctly set to 4000")
    else:
        log_fail(f"Surface moins_10000: saisonnier should be 4000, got {saisonnier}")
        all_passed = False
    
    # Test 3: Set surface to null -> saisonnier should be empty
    log_info("Setting surface category to null...")
    response = session.patch(f"{BASE_URL}/dataset/{upload_id}/surface", json={"category": None})
    if response.status_code != 200:
        log_fail(f"Failed to set surface category: {response.status_code}")
        return False
    
    response = session.get(f"{BASE_URL}/dataset/{upload_id}")
    if response.status_code != 200:
        log_fail(f"Failed to get dataset: {response.status_code}")
        return False
    
    data = response.json()
    recap_rows = data.get("data", {}).get("recap", [])
    
    support_row = None
    for row in recap_rows:
        if "support individuel alu sa" in (row.get("designation") or "").lower():
            support_row = row
            break
    
    if not support_row:
        log_fail("Could not find 'Support individuel alu SA' row")
        return False
    
    saisonnier = support_row.get("saisonnier")
    log_info(f"Surface=null: saisonnier={saisonnier}")
    
    if saisonnier == "" or saisonnier == 0:
        log_pass("Surface null: saisonnier correctly empty")
    else:
        log_fail(f"Surface null: saisonnier should be empty, got {saisonnier}")
        all_passed = False
    
    # Verify SA 2.1 (noir) still gets its saisonnier (no regression)
    log_info("Verifying SA 2.1 (noir) saisonnier (regression check)...")
    
    # Set surface back to plus_10000
    response = session.patch(f"{BASE_URL}/dataset/{upload_id}/surface", json={"category": "plus_10000"})
    response = session.get(f"{BASE_URL}/dataset/{upload_id}")
    data = response.json()
    recap_rows = data.get("data", {}).get("recap", [])
    
    sa_21_row = None
    for row in recap_rows:
        if (row.get("designation") or "").lower() == "sa 2.1 (noir)":
            sa_21_row = row
            break
    
    if sa_21_row:
        sa_21_saisonnier = sa_21_row.get("saisonnier")
        log_info(f"SA 2.1 (noir) saisonnier with plus_10000: {sa_21_saisonnier}")
        if sa_21_saisonnier == 4800:
            log_pass("SA 2.1 (noir) saisonnier correctly set to 4800 (no regression)")
        else:
            log_fail(f"SA 2.1 (noir) saisonnier should be 4800, got {sa_21_saisonnier}")
            all_passed = False
    else:
        log_info("SA 2.1 (noir) row not found (may not exist in this dataset)")
    
    return all_passed

def main():
    """Main test runner."""
    print(f"\n{Colors.BLUE}{'='*70}")
    print(f"VT/Phasage Carrefour Backend Test Suite")
    print(f"Backend URL: {BASE_URL}")
    print(f"{'='*70}{Colors.RESET}\n")
    
    # Create session for auth
    session = requests.Session()
    
    # Login
    log_step("Authentication")
    log_info(f"Logging in as {ADMIN_EMAIL}...")
    
    login_response = session.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    
    if login_response.status_code != 200:
        log_fail(f"Login failed: {login_response.status_code} - {login_response.text}")
        sys.exit(1)
    
    log_pass(f"Logged in successfully as {ADMIN_EMAIL}")
    
    # Run tests
    results = {}
    
    # Step 1: Upload Excel
    upload_id = test_step_1_upload_excel(session)
    if not upload_id:
        log_fail("Cannot proceed without upload_id")
        sys.exit(1)
    results["step_1_upload"] = True
    
    # Step 2: Anti-cache headers
    results["step_2_anti_cache"] = test_step_2_anti_cache_headers(session, upload_id)
    
    # Step 3: Determinism
    results["step_3_determinism"] = test_step_3_determinism(session, upload_id)
    
    # Step 4: MOQ refs
    results["step_4_moq"] = test_step_4_moq_refs(session, upload_id)
    
    # Step 5: Saisonnier support
    results["step_5_saisonnier"] = test_step_5_saisonnier_support(session, upload_id)
    
    # Summary
    print(f"\n{Colors.BLUE}{'='*70}")
    print("TEST SUMMARY")
    print(f"{'='*70}{Colors.RESET}\n")
    
    for step, passed in results.items():
        status = f"{Colors.GREEN}PASS{Colors.RESET}" if passed else f"{Colors.RED}FAIL{Colors.RESET}"
        print(f"{step}: {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print(f"\n{Colors.GREEN}{'='*70}")
        print("ALL TESTS PASSED ✓")
        print(f"{'='*70}{Colors.RESET}\n")
        sys.exit(0)
    else:
        print(f"\n{Colors.RED}{'='*70}")
        print("SOME TESTS FAILED ✗")
        print(f"{'='*70}{Colors.RESET}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
