"""
King County ZIP Header Inspector  v1.1
=======================================
Lists all CSV files and column headers inside the King County bulk data ZIPs.
Run this from the same folder as your ZIPs. It just prints, it doesn't
change anything.

v1.1 Changes:
    - Added Real Property Sales.zip to the inspection list

Usage:
    python kc_zip_headers.py

Output:
    For each ZIP found:
      - ZIP file name
      - CSV file(s) inside
      - Row 1 (the column headers) of each CSV
"""

import os
import sys
import zipfile
import csv
from io import TextIOWrapper


ZIPS_TO_INSPECT = [
    "Residential Building.zip",
    "Parcel.zip",
    "Real Property Account.zip",
    "Real Property Sales.zip",
    "Value History.zip",
]


def inspect_zip(zip_path):
    """Print the CSV files and their header rows from a ZIP."""
    print(f"\n{'=' * 70}")
    print(f"  {os.path.basename(zip_path)}")
    print(f"{'=' * 70}")

    if not os.path.exists(zip_path):
        print(f"  [NOT FOUND] {zip_path}")
        return

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            csv_files = [f for f in zf.namelist() if f.lower().endswith('.csv')]

            if not csv_files:
                print(f"  [WARNING] No CSV files inside this ZIP")
                print(f"  Files present: {zf.namelist()}")
                return

            for csv_name in csv_files:
                print(f"\n  CSV file: {csv_name}")
                try:
                    with zf.open(csv_name) as f:
                        reader = csv.reader(
                            TextIOWrapper(f, encoding='utf-8', errors='replace')
                        )
                        header = next(reader, None)
                        if header:
                            print(f"  Column count: {len(header)}")
                            print(f"  Headers:")
                            for i, col in enumerate(header, 1):
                                print(f"    {i:3}. {col}")
                        else:
                            print(f"  [WARNING] File is empty")
                except Exception as e:
                    print(f"  [ERROR] Could not read CSV: {e}")

    except zipfile.BadZipFile:
        print(f"  [ERROR] Not a valid ZIP file")
    except Exception as e:
        print(f"  [ERROR] {e}")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if not script_dir:
        script_dir = os.getcwd()

    print("King County ZIP Header Inspector v1.1")
    print(f"Looking in: {script_dir}")

    for zip_name in ZIPS_TO_INSPECT:
        zip_path = os.path.join(script_dir, zip_name)
        inspect_zip(zip_path)

    print(f"\n{'=' * 70}")
    print("  Done.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
