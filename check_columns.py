"""
Check what columns are in the King County CSV files
"""
import os
import zipfile
import csv
from io import TextIOWrapper

script_dir = os.path.dirname(os.path.abspath(__file__))

files_to_check = [
    ("Parcel.zip", "EXTR_Parcel.csv"),
    ("Residential Building.zip", "EXTR_ResBldg.csv"),
    ("Real Property Account.zip", "EXTR_RPAcct.csv"),
]

for zip_name, csv_name in files_to_check:
    zip_path = os.path.join(script_dir, zip_name)
    print(f"\n{'='*60}")
    print(f"FILE: {zip_name}")
    print(f"{'='*60}")
    
    if not os.path.exists(zip_path):
        print(f"  NOT FOUND")
        continue
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            csv_files = [f for f in zf.namelist() if f.endswith('.csv')]
            print(f"  CSV files in ZIP: {csv_files}")
            
            if csv_files:
                target = csv_files[0]
                with zf.open(target) as f:
                    reader = csv.DictReader(TextIOWrapper(f, encoding='utf-8', errors='replace'))
                    
                    # Get column names
                    columns = reader.fieldnames
                    print(f"\n  COLUMNS ({len(columns)}):")
                    for col in columns:
                        print(f"    - {col}")
                    
                    # Get first row as sample
                    print(f"\n  SAMPLE ROW:")
                    for row in reader:
                        for key, val in row.items():
                            if val:
                                print(f"    {key}: {val[:50] if len(str(val)) > 50 else val}")
                        break
    except Exception as e:
        print(f"  ERROR: {e}")
