"""
King County Property Lookup Tool  v1.2
======================================
Looks up King County property data from bulk data files downloaded from:
https://info.kingcounty.gov/assessor/DataDownload/default.aspx

Full version history: see CHANGELOG.md in the project root.

Recent changes (v1.2):
    - Fixed: Value History now uses 'TaxYr' column (was 'TaxYear')
    - Added: Sales history loader (Real Property Sales.zip)
    - Added: Row-count sanity check on every loader
    - Fixed: Property Address now single-spaced

Required ZIP files (place in same folder as this script):
    - Residential Building.zip  (addresses, beds, baths, sqft, year built)
    - Parcel.zip                (lot size, plat name, views, waterfront)
    - Real Property Account.zip (billing address - no taxpayer names in public version)
    - Real Property Sales.zip   (sale date, price, grantor/grantee)
    - Value History.zip         (assessed values by year)

Usage:
    python kc_lookup.py "7214 204th Dr NE"
    python kc_lookup.py "3546 SW 99th St"
"""

import os
import sys
import re
import zipfile
import csv
from io import TextIOWrapper


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# ZIP file names (as downloaded from King County)
RESBLDG_ZIP = "Residential Building.zip"
PARCEL_ZIP = "Parcel.zip"
RPACCT_ZIP = "Real Property Account.zip"
SALES_ZIP = "Real Property Sales.zip"
VALUE_ZIP = "Value History.zip"

# CSV file names inside the ZIPs
RESBLDG_CSV = "EXTR_ResBldg.csv"
PARCEL_CSV = "EXTR_Parcel.csv"
RPACCT_CSV = "EXTR_RPAcct_NoName.csv"  # Public version has no taxpayer names
SALES_CSV = "EXTR_RPSale.csv"
VALUE_CSV = "EXTR_ValueHistory.csv"

# Sanity check: warn if loader skips more than this fraction of rows.
# Catches silent schema changes (e.g. King County renames a column).
ROW_LOAD_WARN_THRESHOLD = 0.90  # warn if < 90% of rows load


# ═══════════════════════════════════════════════════════════════════════════════
#  ADDRESS NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_address(addr):
    """Normalize address for matching. Returns uppercase, compressed spaces,
    with common abbreviations standardized."""
    if not addr:
        return ""
    
    # Uppercase and compress whitespace
    addr = " ".join(addr.upper().split())
    
    # Remove zip code from end if present
    addr = re.sub(r'\s+\d{5}(-\d{4})?$', '', addr)
    
    # Standardize directional prefixes/suffixes
    addr = re.sub(r'\bNORTHWEST\b', 'NW', addr)
    addr = re.sub(r'\bNORTHEAST\b', 'NE', addr)
    addr = re.sub(r'\bSOUTHWEST\b', 'SW', addr)
    addr = re.sub(r'\bSOUTHEAST\b', 'SE', addr)
    addr = re.sub(r'\bNORTH\b', 'N', addr)
    addr = re.sub(r'\bSOUTH\b', 'S', addr)
    addr = re.sub(r'\bEAST\b', 'E', addr)
    addr = re.sub(r'\bWEST\b', 'W', addr)
    
    # Standardize street types
    addr = re.sub(r'\bSTREET\b', 'ST', addr)
    addr = re.sub(r'\bAVENUE\b', 'AVE', addr)
    addr = re.sub(r'\bDRIVE\b', 'DR', addr)
    addr = re.sub(r'\bROAD\b', 'RD', addr)
    addr = re.sub(r'\bLANE\b', 'LN', addr)
    addr = re.sub(r'\bCOURT\b', 'CT', addr)
    addr = re.sub(r'\bPLACE\b', 'PL', addr)
    addr = re.sub(r'\bBOULEVARD\b', 'BLVD', addr)
    addr = re.sub(r'\bCIRCLE\b', 'CIR', addr)
    addr = re.sub(r'\bTERRACE\b', 'TER', addr)
    addr = re.sub(r'\bPARKWAY\b', 'PKWY', addr)
    addr = re.sub(r'\bHIGHWAY\b', 'HWY', addr)
    addr = re.sub(r'\bWAY\b', 'WY', addr)
    
    # Remove ordinal suffixes (1ST -> 1, 2ND -> 2, etc.) for matching flexibility
    # Actually, keep them but standardize: 1ST, 2ND, 3RD, 4TH, etc.
    
    return addr


def extract_street_number(addr):
    """Extract the street number from an address for partial matching."""
    match = re.match(r'^(\d+)', addr)
    return match.group(1) if match else ""


# ═══════════════════════════════════════════════════════════════════════════════
#  CSV READING FROM ZIP
# ═══════════════════════════════════════════════════════════════════════════════

def read_csv_from_zip(zip_path, csv_name):
    """Read a CSV file directly from a ZIP archive without extracting.
    Returns a list of dictionaries (one per row)."""
    rows = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Find the CSV file (might have different casing or be in a subfolder)
        csv_files = [f for f in zf.namelist() if f.lower().endswith('.csv')]
        
        # Try exact match first
        target = None
        for f in csv_files:
            if f.lower() == csv_name.lower() or f.lower().endswith('/' + csv_name.lower()):
                target = f
                break
        
        # If no exact match, use the first CSV found
        if not target and csv_files:
            target = csv_files[0]
            print(f"  Note: Using {target} (expected {csv_name})")
        
        if not target:
            print(f"  [WARNING] No CSV found in {zip_path}")
            return rows
        
        with zf.open(target) as f:
            # Handle potential encoding issues
            reader = csv.DictReader(TextIOWrapper(f, encoding='utf-8', errors='replace'))
            for row in reader:
                rows.append(row)
    
    return rows


def _sanity_check_load(loader_name, loaded_count, total_rows):
    """Warn if fewer than ROW_LOAD_WARN_THRESHOLD of rows were loaded.
    Catches silent schema breaks (e.g., renamed columns making every row
    get skipped). Returns True if healthy, False if suspicious."""
    if total_rows == 0:
        print(f"  [WARNING] {loader_name}: source CSV had 0 rows")
        return False
    ratio = loaded_count / total_rows
    if ratio < ROW_LOAD_WARN_THRESHOLD:
        pct = ratio * 100
        print(f"  [WARNING] {loader_name}: only loaded {loaded_count:,} of "
              f"{total_rows:,} rows ({pct:.1f}%). Possible column-name change "
              f"in the source file. Check the KC schema.")
        return False
    return True


def _collapse_spaces(text):
    """Collapse multiple whitespace characters into single spaces and strip."""
    if not text:
        return text
    return " ".join(text.split())


# ═══════════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

def load_resbldg_data(script_dir):
    """Load residential building data and build address index.
    Returns (address_index, pin_to_building) where:
        - address_index maps normalized_address -> PIN
        - pin_to_building maps PIN -> building details dict
    """
    zip_path = os.path.join(script_dir, RESBLDG_ZIP)
    if not os.path.exists(zip_path):
        print(f"  [WARNING] {RESBLDG_ZIP} not found")
        return {}, {}
    
    print(f"Loading residential building data from {RESBLDG_ZIP}...")
    rows = read_csv_from_zip(zip_path, RESBLDG_CSV)
    
    address_index = {}  # normalized_address -> PIN
    pin_to_building = {}  # PIN -> building data
    processed = 0  # count of rows that parsed successfully (for sanity check)
    
    for row in rows:
        major = row.get('Major', '').strip()
        minor = row.get('Minor', '').strip()
        
        if not major or not minor:
            continue
        
        # Build PIN (10 digits: 6-digit major + 4-digit minor)
        pin = f"{major.zfill(6)}{minor.zfill(4)}"
        processed += 1
        
        # Get address from the Address column
        address = row.get('Address', '').strip()
        if address:
            norm_addr = normalize_address(address)
            if norm_addr:
                address_index[norm_addr] = pin
        
        # Store building details
        pin_to_building[pin] = {
            'Address': address,
            'YrBuilt': row.get('YrBuilt', ''),
            'Stories': row.get('Stories', ''),
            'SqFtTotLiving': row.get('SqFtTotLiving', ''),
            'Bedrooms': row.get('Bedrooms', ''),
            'BathFullCount': row.get('BathFullCount', ''),
            'Bath3qtrCount': row.get('Bath3qtrCount', ''),
            'BathHalfCount': row.get('BathHalfCount', ''),
            'BldgGrade': row.get('BldgGrade', ''),
            'Condition': row.get('Condition', ''),
            'HeatSystem': row.get('HeatSystem', ''),
            'SqFtGarageAttached': row.get('SqFtGarageAttached', ''),
            'SqFtTotBasement': row.get('SqFtTotBasement', ''),
            'SqFtFinBasement': row.get('SqFtFinBasement', ''),
            'ViewUtilization': row.get('ViewUtilization', ''),
            'ZipCode': row.get('ZipCode', ''),
        }
    
    print(f"  Loaded {len(rows)} buildings, {len(address_index)} unique addresses")
    _sanity_check_load("Residential Building", processed, len(rows))
    return address_index, pin_to_building


def load_parcel_data(script_dir):
    """Load parcel data. Returns dict mapping PIN -> parcel details."""
    zip_path = os.path.join(script_dir, PARCEL_ZIP)
    if not os.path.exists(zip_path):
        print(f"  [WARNING] {PARCEL_ZIP} not found")
        return {}
    
    print(f"Loading parcel data from {PARCEL_ZIP}...")
    rows = read_csv_from_zip(zip_path, PARCEL_CSV)
    
    pin_to_parcel = {}
    for row in rows:
        major = row.get('Major', '').strip()
        minor = row.get('Minor', '').strip()
        
        if not major or not minor:
            continue
        
        pin = f"{major.zfill(6)}{minor.zfill(4)}"
        
        # Combine view flags into a readable string
        views = []
        if row.get('MtRainier', '0') not in ('0', '', 'N'):
            views.append('Mt Rainier')
        if row.get('Olympics', '0') not in ('0', '', 'N'):
            views.append('Olympics')
        if row.get('Cascades', '0') not in ('0', '', 'N'):
            views.append('Cascades')
        if row.get('Territorial', '0') not in ('0', '', 'N'):
            views.append('Territorial')
        if row.get('SeattleSkyline', '0') not in ('0', '', 'N'):
            views.append('Seattle Skyline')
        if row.get('PugetSound', '0') not in ('0', '', 'N'):
            views.append('Puget Sound')
        if row.get('LakeWashington', '0') not in ('0', '', 'N'):
            views.append('Lake Washington')
        if row.get('LakeSammamish', '0') not in ('0', '', 'N'):
            views.append('Lake Sammamish')
        
        # Waterfront
        wfnt = row.get('WfntFootage', '0')
        waterfront = "Yes" if wfnt and wfnt != '0' else "No"
        
        pin_to_parcel[pin] = {
            'PlatName': row.get('PlatName', ''),
            'SqFtLot': row.get('SqFtLot', ''),
            'DistrictName': row.get('DistrictName', ''),
            'LevyCode': row.get('LevyCode', ''),
            'CurrentZoning': row.get('CurrentZoning', ''),
            'PresentUse': row.get('PresentUse', ''),
            'Views': ', '.join(views) if views else '',
            'Waterfront': waterfront,
            'WfntFootage': wfnt,
        }
    
    print(f"  Loaded {len(pin_to_parcel)} parcels")
    _sanity_check_load("Parcel", len(pin_to_parcel), len(rows))
    return pin_to_parcel


def load_rpacct_data(script_dir):
    """Load real property account data. Returns dict mapping PIN -> account details."""
    zip_path = os.path.join(script_dir, RPACCT_ZIP)
    if not os.path.exists(zip_path):
        print(f"  [WARNING] {RPACCT_ZIP} not found")
        return {}
    
    print(f"Loading account data from {RPACCT_ZIP}...")
    rows = read_csv_from_zip(zip_path, RPACCT_CSV)
    
    pin_to_acct = {}
    for row in rows:
        major = row.get('Major', '').strip()
        minor = row.get('Minor', '').strip()
        
        if not major or not minor:
            continue
        
        pin = f"{major.zfill(6)}{minor.zfill(4)}"
        
        # Build billing address
        addr_line = row.get('AddrLine', '').strip()
        city_state = row.get('CityState', '').strip()
        zip_code = row.get('ZipCode', '').strip()
        
        billing_addr = addr_line
        if city_state:
            billing_addr += f", {city_state}"
        if zip_code:
            billing_addr += f" {zip_code}"
        
        pin_to_acct[pin] = {
            'BillingAddress': billing_addr,
            'TaxStat': row.get('TaxStat', ''),
            'ApprLandVal': row.get('ApprLandVal', ''),
            'ApprImpsVal': row.get('ApprImpsVal', ''),
            'TaxableLandVal': row.get('TaxableLandVal', ''),
            'TaxableImpsVal': row.get('TaxableImpsVal', ''),
        }
    
    print(f"  Loaded {len(pin_to_acct)} accounts")
    _sanity_check_load("Real Property Account", len(pin_to_acct), len(rows))
    return pin_to_acct


def load_value_data(script_dir):
    """Load value history data. Returns dict mapping PIN -> most recent values."""
    zip_path = os.path.join(script_dir, VALUE_ZIP)
    if not os.path.exists(zip_path):
        print(f"  [WARNING] {VALUE_ZIP} not found")
        return {}
    
    print(f"Loading value history from {VALUE_ZIP}...")
    rows = read_csv_from_zip(zip_path, VALUE_CSV)
    
    # Track most recent year per PIN
    pin_to_value = {}
    processed = 0  # rows that parsed OK (used for sanity check, since we
                   # intentionally keep only the latest year per PIN)
    for row in rows:
        major = row.get('Major', '').strip()
        minor = row.get('Minor', '').strip()
        # v1.2 FIX: column is 'TaxYr' in the KC schema, not 'TaxYear'
        tax_year = row.get('TaxYr', '').strip()
        
        if not major or not minor or not tax_year:
            continue
        
        pin = f"{major.zfill(6)}{minor.zfill(4)}"
        
        try:
            year = int(tax_year)
        except ValueError:
            continue
        
        processed += 1
        
        # Keep only the most recent year
        if pin in pin_to_value:
            if year <= pin_to_value[pin].get('_year', 0):
                continue
        
        pin_to_value[pin] = {
            '_year': year,
            'TaxYear': tax_year,
            'ApprTotVal': row.get('ApprLandVal', ''),  # will recompute below
            'ApprLandVal': row.get('ApprLandVal', ''),
            'ApprImpsVal': row.get('ApprImpsVal', ''),
            'TaxableTotVal': row.get('LandVal', ''),   # will recompute below
            'LandVal': row.get('LandVal', ''),
            'ImpsVal': row.get('ImpsVal', ''),
        }
    
    # Compute ApprTotVal (land + improvements) and TaxableTotVal for each entry.
    # King County's value history doesn't store a pre-computed total; it stores
    # the two components separately. We add them here.
    for pin, v in pin_to_value.items():
        try:
            appr_total = int(v.get('ApprLandVal') or 0) + int(v.get('ApprImpsVal') or 0)
            v['ApprTotVal'] = str(appr_total) if appr_total else ''
        except (ValueError, TypeError):
            v['ApprTotVal'] = ''
        try:
            tax_total = int(v.get('LandVal') or 0) + int(v.get('ImpsVal') or 0)
            v['TaxableTotVal'] = str(tax_total) if tax_total else ''
        except (ValueError, TypeError):
            v['TaxableTotVal'] = ''
        v.pop('_year', None)
    
    print(f"  Loaded values for {len(pin_to_value):,} parcels (from {processed:,} rows)")
    _sanity_check_load("Value History", processed, len(rows))
    return pin_to_value


def load_sales_data(script_dir):
    """Load real property sales history. Returns dict mapping PIN -> list of
    sale records (sorted newest first)."""
    zip_path = os.path.join(script_dir, SALES_ZIP)
    if not os.path.exists(zip_path):
        print(f"  [WARNING] {SALES_ZIP} not found")
        return {}
    
    print(f"Loading sales history from {SALES_ZIP}...")
    rows = read_csv_from_zip(zip_path, SALES_CSV)
    
    pin_to_sales = {}
    loaded = 0
    for row in rows:
        major = row.get('Major', '').strip()
        minor = row.get('Minor', '').strip()
        
        if not major or not minor:
            continue
        
        pin = f"{major.zfill(6)}{minor.zfill(4)}"
        
        sale = {
            'DocumentDate': row.get('DocumentDate', '').strip(),
            'SalePrice':    row.get('SalePrice', '').strip(),
            'SellerName':   row.get('SellerName', '').strip(),
            'BuyerName':    row.get('BuyerName', '').strip(),
            'SaleInstrument': row.get('SaleInstrument', '').strip(),
            'SaleReason':   row.get('SaleReason', '').strip(),
            'SaleWarning':  row.get('SaleWarning', '').strip(),
            'ExciseTaxNbr': row.get('ExciseTaxNbr', '').strip(),
        }
        
        pin_to_sales.setdefault(pin, []).append(sale)
        loaded += 1
    
    # Sort each PIN's sales newest first (DocumentDate is MM/DD/YYYY)
    def _date_key(s):
        d = s.get('DocumentDate', '')
        # Convert MM/DD/YYYY to YYYYMMDD for sorting. Unparseable dates go last.
        m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4})', d)
        if m:
            mm, dd, yyyy = m.groups()
            return f"{yyyy}{mm.zfill(2)}{dd.zfill(2)}"
        return "00000000"
    
    for pin in pin_to_sales:
        pin_to_sales[pin].sort(key=_date_key, reverse=True)
    
    print(f"  Loaded {loaded:,} sales across {len(pin_to_sales):,} parcels")
    _sanity_check_load("Real Property Sales", loaded, len(rows))
    return pin_to_sales


# ═══════════════════════════════════════════════════════════════════════════════
#  ADDRESS SEARCH
# ═══════════════════════════════════════════════════════════════════════════════

def find_address(search_addr, address_index):
    """Find a property by address. Returns PIN or None.
    Tries exact match first, then partial matching."""
    
    norm_search = normalize_address(search_addr)
    
    # Exact match
    if norm_search in address_index:
        return address_index[norm_search]
    
    # Try without street type suffix
    search_no_suffix = re.sub(r'\s+(ST|AVE|DR|RD|LN|CT|PL|BLVD|CIR|TER|PKWY|HWY|WY)$', '', norm_search)
    for addr, pin in address_index.items():
        addr_no_suffix = re.sub(r'\s+(ST|AVE|DR|RD|LN|CT|PL|BLVD|CIR|TER|PKWY|HWY|WY)$', '', addr)
        if search_no_suffix == addr_no_suffix:
            return pin
    
    # Try matching just the street number + first word of street name
    search_number = extract_street_number(norm_search)
    if search_number:
        search_parts = norm_search.split()
        if len(search_parts) >= 2:
            # Get street name (skip direction prefix if present)
            street_start = 1
            if search_parts[1] in ('N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW'):
                street_start = 2
            
            if len(search_parts) > street_start:
                search_street = search_parts[street_start]
                
                matches = []
                for addr, pin in address_index.items():
                    if addr.startswith(search_number + ' ') and search_street in addr:
                        matches.append((addr, pin))
                
                if len(matches) == 1:
                    return matches[0][1]
                elif len(matches) > 1:
                    print(f"  Multiple matches found for '{search_addr}':")
                    for addr, pin in matches[:5]:
                        print(f"    - {addr}")
                    if len(matches) > 5:
                        print(f"    ... and {len(matches) - 5} more")
    
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  LOOKUP ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════════

def lookup_property(search_addr, address_index, pin_to_building, pin_to_parcel,
                    pin_to_acct, pin_to_value, pin_to_sales):
    """Look up a property by address and combine data from all sources.
    Returns a dict with all available property data, or None if not found."""
    
    pin = find_address(search_addr, address_index)
    if not pin:
        return None
    
    result = {
        'PIN': pin,
        'Parcel Number': f"{pin[:6]}-{pin[6:]}",  # Format as XXXXXX-XXXX
    }
    
    # Building data (primary - has the address)
    building = pin_to_building.get(pin, {})
    if building:
        # v1.2: collapse the padded spacing KC uses in its address field
        result['Property Address'] = _collapse_spaces(building.get('Address', ''))
        result['Year Built'] = building.get('YrBuilt', '')
        result['Stories'] = building.get('Stories', '')
        result['Total Finished SF'] = building.get('SqFtTotLiving', '')
        result['Bedrooms'] = building.get('Bedrooms', '')
        result['Full Baths'] = building.get('BathFullCount', '')
        result['3/4 Baths'] = building.get('Bath3qtrCount', '')
        result['Half Baths'] = building.get('BathHalfCount', '')
        result['Property Grade'] = building.get('BldgGrade', '')
        result['Property Condition'] = building.get('Condition', '')
        result['Heat System'] = building.get('HeatSystem', '')
        result['Garage SF'] = building.get('SqFtGarageAttached', '')
        result['Basement SF'] = building.get('SqFtTotBasement', '')
        result['Finished Basement SF'] = building.get('SqFtFinBasement', '')
        result['Zip Code'] = building.get('ZipCode', '')
    
    # Parcel data
    parcel = pin_to_parcel.get(pin, {})
    if parcel:
        result['Subdivision Name'] = parcel.get('PlatName', '')
        result['Lot Size SF'] = parcel.get('SqFtLot', '')
        result['District'] = parcel.get('DistrictName', '')
        result['Zoning'] = parcel.get('CurrentZoning', '')
        result['Present Use'] = parcel.get('PresentUse', '')
        result['Views'] = parcel.get('Views', '')
        result['Waterfront'] = parcel.get('Waterfront', '')
    
    # Account data (billing address)
    acct = pin_to_acct.get(pin, {})
    if acct:
        result['Tax Billing Address'] = acct.get('BillingAddress', '')
        result['Tax Status'] = acct.get('TaxStat', '')
    
    # Value data
    value = pin_to_value.get(pin, {})
    if value:
        result['Tax Year'] = value.get('TaxYear', '')
        result['Appraised Total'] = value.get('ApprTotVal', '')
        result['Appraised Land'] = value.get('ApprLandVal', '')
        result['Appraised Improvements'] = value.get('ApprImpsVal', '')
        result['Taxable Value'] = value.get('TaxableTotVal', '')
    
    # Sales history (v1.2 new). Show the most recent sale plus a full history list.
    sales = pin_to_sales.get(pin, [])
    if sales:
        most_recent = sales[0]
        result['Most Recent Sale Date']   = most_recent.get('DocumentDate', '')
        result['Most Recent Sale Amount'] = most_recent.get('SalePrice', '')
        result['Most Recent Seller']      = most_recent.get('SellerName', '')
        result['Most Recent Buyer']       = most_recent.get('BuyerName', '')
        result['Most Recent Sale Instrument'] = most_recent.get('SaleInstrument', '')
        result['Most Recent Sale Warning']    = most_recent.get('SaleWarning', '')
        # Full history as a single semicolon-separated string (matches Snohomish format)
        result['Sales History'] = "; ".join(
            f"{s.get('DocumentDate','')} - ${s.get('SalePrice','')} "
            f"({s.get('SaleInstrument','')}) {s.get('SellerName','')} -> "
            f"{s.get('BuyerName','')}"
            for s in sales
        )
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if len(sys.argv) < 2:
        print("Usage: python kc_lookup.py \"<address>\"")
        print("Example: python kc_lookup.py \"7214 204th Dr NE\"")
        sys.exit(1)
    
    search_addr = " ".join(sys.argv[1:])
    
    print("King County Property Lookup")
    print("=" * 50)
    print(f"Searching for: {search_addr}")
    print()
    
    # Load all data
    address_index, pin_to_building = load_resbldg_data(script_dir)
    pin_to_parcel = load_parcel_data(script_dir)
    pin_to_acct = load_rpacct_data(script_dir)
    pin_to_value = load_value_data(script_dir)
    pin_to_sales = load_sales_data(script_dir)
    
    print()
    print(f"Searching for: {search_addr}")
    print("=" * 50)
    
    result = lookup_property(
        search_addr, 
        address_index, 
        pin_to_building, 
        pin_to_parcel, 
        pin_to_acct, 
        pin_to_value,
        pin_to_sales,
    )
    
    if result:
        print("\nPROPERTY FOUND:")
        print("-" * 50)
        for key, val in result.items():
            if val:  # Only show non-empty fields
                print(f"  {key}: {val}")
    else:
        print(f"\n[ERROR] No property found for: {search_addr}")
        print("Try a different address format or check spelling.")


if __name__ == "__main__":
    main()
