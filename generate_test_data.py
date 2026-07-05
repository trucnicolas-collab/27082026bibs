#!/usr/bin/env python3
"""Generate test data for the wizard UI testing."""
import openpyxl
from PIL import Image
import io

# Generate Excel file with required columns
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Data"

# EXACT header row as required
headers = ["Secteur", "Rayon", "N° allée", "Type", "Référence", "Désignation", "Quantité"]
ws.append(headers)

# Add test data rows including EEG rows and a NON-numeric reference row
test_data = [
    ["Frais", "Fruits", "A1", "EEG", "13469", "ES 1.5 (noir)", 150],
    ["Frais", "Légumes", "A2", "EEG", "17740", "ES 2.1 (noir)", 250],
    ["Épicerie", "Conserves", "B1", "EEG", "12345", "SA 2.1 (noir)", 180],
    ["Épicerie", "Pâtes", "B2", "EEG", "12346", "SA 1.5 (noir)", 120],
    ["Textile", "Vêtements", "C1", "Rail", "98765", "Rail ES 1.5m", 50],
    ["Textile", "Chaussures", "C2", "Fixation", "AUTRE1", "Support AUTRE", 30],  # NON-numeric ref
    ["Bazar", "Jouets", "D1", "EEG", "11111", "ES 1.5 (noir)", 100],
    ["Bazar", "Papeterie", "D2", "EEG", "22222", "SA 2.1 (noir)", 90],
]

for row in test_data:
    ws.append(row)

# Save Excel file
excel_path = "/tmp/test_wizard_data.xlsx"
wb.save(excel_path)
print(f"✓ Excel file created: {excel_path}")

# Generate small PNG images for wifi plan testing
def create_test_image(filename, color, text):
    """Create a small test image."""
    img = Image.new('RGB', (400, 300), color=color)
    img_path = f"/tmp/{filename}"
    img.save(img_path, 'PNG')
    print(f"✓ Image created: {img_path}")
    return img_path

# Create 2 test images
create_test_image("wifi_plan_1.png", (100, 150, 200), "Plan 1")
create_test_image("wifi_plan_2.png", (200, 100, 150), "Plan 2")

print("\n✓ All test data generated successfully!")
