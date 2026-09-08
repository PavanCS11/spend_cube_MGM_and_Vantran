import pandas as pd
import os
import sys
import re

# Add root to python path to allow imports if needed
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
STAGING_FILE = os.path.join(BASE_DIR, "step_2_enrichment", "b.staging", "pre_cleaned_staging.csv")
VENDOR_MAP_FILE = os.path.join(BASE_DIR, "step_3_maintenance", "a.mappings", "vendor_map.csv")
ITEM_MAP_FILE = os.path.join(BASE_DIR, "step_3_maintenance", "a.mappings", "item_map.csv")
MASTER_TAXONOMY_FILE = os.path.join(BASE_DIR, "step_3_maintenance", "a.mappings", "master_taxonomy.xlsx")
VANTRAN_SOURCE_SYSTEM = "NETSUITE_VANTRAN"


def normalize_item_id(value) -> str:
    """Normalize item IDs for stable matching across runs."""
    if pd.isna(value):
        return ''
    s = str(value).strip()
    if s.lower() in {'', 'nan', 'none'}:
        return ''
    # Normalize Excel/CSV float-like integers (e.g., 18020.0 -> 18020)
    if s.endswith('.0'):
        try:
            return str(int(float(s)))
        except Exception:
            pass
    return s


def description_quality(raw_desc, item_id) -> int:
    """Higher score means better, more informative description."""
    desc = '' if pd.isna(raw_desc) else str(raw_desc).strip()
    item = '' if pd.isna(item_id) else str(item_id).strip()
    if not desc or desc in {'[FILL IN DESCRIPTION]', 'nan', 'None'}:
        return 0
    if desc == item:
        return 1
    return 2 + min(len(desc), 200)

def load_csv(path):
    if os.path.exists(path):
        try:
            return pd.read_csv(path, keep_default_na=False)
        except pd.errors.EmptyDataError:
            print(f"Warning: {path} is empty. Treating as new.")
            return None
    return None


def sanitize_item_map_columns(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Normalize and sanitize item_map columns to keep Power BI schema stable."""
    if df is None or df.empty:
        return df

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Drop CSV artifacts like unnamed index columns.
    drop_cols = [c for c in df.columns if c.startswith('Unnamed:')]

    # Drop pandas-mangled duplicate headers (e.g., Category_Level_4.1) when base exists.
    for col in df.columns:
        match = re.match(r'^(.*)\.(\d+)$', col)
        if match and match.group(1) in df.columns:
            drop_cols.append(col)

    if drop_cols:
        unique_drop = sorted(set(drop_cols))
        df = df.drop(columns=unique_drop, errors='ignore')
        print(f"Dropped {len(unique_drop)} schema artifact columns from {label}: {unique_drop}")

    # Keep first occurrence if any exact duplicate headers remain.
    if df.columns.duplicated().any():
        dup_count = int(df.columns.duplicated().sum())
        df = df.loc[:, ~df.columns.duplicated()].copy()
        print(f"Dropped {dup_count} duplicated column headers from {label}.")

    return df


def sanitize_vendor_map_rows(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Drop blank/duplicate vendor-map rows so refresh does not preserve junk entries."""
    if df is None or df.empty:
        return df

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    if 'Raw_Name' not in df.columns:
        return df

    df['Raw_Name'] = df['Raw_Name'].astype(str).str.strip()
    if 'Standardized_Name' in df.columns:
        df['Standardized_Name'] = df['Standardized_Name'].astype(str).str.strip()

    raw_lower = df['Raw_Name'].astype(str).str.strip().str.lower()
    blank_mask = raw_lower.isin(['', 'nan', 'none', 'n/a'])
    blank_count = int(blank_mask.sum())
    if blank_count > 0:
        df = df.loc[~blank_mask].copy()
        print(f"Dropped {blank_count:,} blank Raw_Name rows from {label}.")

    dup_count = int(df.duplicated(subset=['Raw_Name'], keep='first').sum())
    if dup_count > 0:
        df = df.drop_duplicates(subset=['Raw_Name'], keep='first').copy()
        print(f"Dropped {dup_count:,} duplicate Raw_Name rows from {label}.")

    return df

def get_best_description(group):
    """
    Get the best description from multiple rows for an item.
    Priority: item_description > item_display_name > item_name_mpn > line_description
    Skips empty strings, placeholder values, and values that match the item_id.
    """
    placeholders = ['', '[FILL IN DESCRIPTION]']
    item_id = str(group['item_id'].iloc[0]) if 'item_id' in group.columns else ''
    # print(f"Finding best description for Item ID: {item_id} (checking {len(group)} rows)")
    # Priority 1: item_description
    if 'item_description' in group.columns:
        for val in group['item_description'].dropna():
            val_str = str(val).strip()
            if val_str and val_str not in placeholders and val_str != item_id:
                return val_str

    # Priority 2: item_display_name
    if 'item_display_name' in group.columns:
        for val in group['item_display_name'].dropna():
            val_str = str(val).strip()
            if val_str and val_str not in placeholders and val_str != item_id:
                return val_str

    # Priority 3: item_name_mpn
    if 'item_name_mpn' in group.columns:
        for val in group['item_name_mpn'].dropna():
            val_str = str(val).strip()
            if val_str and val_str not in placeholders and val_str != item_id:
                return val_str

    # Priority 4: line_description (fallback for Epicor items with no Part Description)
    if 'line_description' in group.columns:
        for val in group['line_description'].dropna():
            val_str = str(val).strip()
            if val_str and val_str not in placeholders and val_str != item_id:
                return val_str

    return ''


def _apply_vantran_taxonomy(df_item_final: pd.DataFrame):
    """
    Populates Category_Level_1 through Category_Level_5 for NETSUITE_VANTRAN items
    from vantran_taxonomy.xlsx.
    Matches on Item_ID (item_map) → Item (taxonomy), stripping any leading '(in) ' prefix.
    Overwrites existing Category_Level_1..5 values for NETSUITE_VANTRAN rows
    when a taxonomy match exists.
    Processes only UNIQUE item IDs for efficiency.
    """
    if not os.path.exists(MASTER_TAXONOMY_FILE):
        print(f"  Warning: Master taxonomy file not found at {MASTER_TAXONOMY_FILE}")
        return

    taxonomy = pd.read_excel(MASTER_TAXONOMY_FILE, sheet_name="MAIN")

    # Build lookup: taxonomy Item → taxonomy levels
    taxonomy['_key'] = taxonomy['Item'].astype(str).str.strip()
    level_cols = [col for col in ['Level 1', 'Level 2', 'Level 3', 'Level 4', 'Level 5'] if col in taxonomy.columns]
    tax_lookup = taxonomy.set_index('_key')[level_cols].to_dict('index')

    # Identify all NETSUITE_VANTRAN rows (overwrite mode)
    vantran_mask = df_item_final.get('source_system', pd.Series('', index=df_item_final.index)) == VANTRAN_SOURCE_SYSTEM
    target_mask = vantran_mask
    target_count = target_mask.sum()

    if target_count == 0:
        print("  No NETSUITE_VANTRAN items found for taxonomy refresh.")
        return

    # Get UNIQUE item IDs that need categories
    unique_item_ids = df_item_final[target_mask]['Item_ID'].unique()
    print(f"  Applying taxonomy to {len(unique_item_ids):,} unique NETSUITE_VANTRAN items ({target_count:,} total rows)...")

    # Build mapping: Item_ID → tax categories
    item_categories = {}
    filled = 0
    for item_id in unique_item_ids:
        raw_id = str(item_id).strip()
        # Strip '(in) ' prefix used in item_map for VanTran items
        lookup_key = raw_id
        # lookup_key = raw_id.removeprefix('(in) ').strip()
        tax_row = tax_lookup.get(lookup_key)
        if tax_row:
            item_categories[raw_id] = {
                'Category_Level_1': tax_row.get('Level 1', ''),
                'Category_Level_2': tax_row.get('Level 2', ''),
                'Category_Level_3': tax_row.get('Level 3', ''),
                'Category_Level_4': tax_row.get('Level 4', ''),
                'Category_Level_5': tax_row.get('Level 5', '')
            }
            filled += 1

    # Apply categories to all matching rows
    for idx in df_item_final[target_mask].index:
        item_id = str(df_item_final.at[idx, 'Item_ID']).strip()
        if item_id in item_categories:
            cats = item_categories[item_id]
            if 'Category_Level_1' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_1'] = cats['Category_Level_1']
            if 'Category_Level_2' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_2'] = cats['Category_Level_2']
            if 'Category_Level_3' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_3'] = cats['Category_Level_3']
            if 'Category_Level_4' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_4'] = cats['Category_Level_4']
            if 'Category_Level_5' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_5'] = cats['Category_Level_5']

    print(f"  Filled categories for {filled:,} unique items ({target_count:,} total rows).")

    if filled < len(unique_item_ids):
        print(f"  Warning: {len(unique_item_ids) - filled:,} unique NETSUITE_VANTRAN items had no match in taxonomy.")


def _apply_syteline_taxonomy(df_item_final: pd.DataFrame):
    """
    Populates Category_Level_1 through Category_Level_5 for SYTELINE items
    from master_taxonomy.xlsx.
    Matches on Item_ID (item_map) → Item (taxonomy), stripping any leading '(in) ' prefix.
    Overwrites existing Category_Level_1..5 values for SYTELINE rows
    when a taxonomy match exists.
    Processes only UNIQUE item IDs for efficiency.
    """
    if not os.path.exists(MASTER_TAXONOMY_FILE):
        print(f"  Warning: Master taxonomy file not found at {MASTER_TAXONOMY_FILE}")
        return

    taxonomy = pd.read_excel(MASTER_TAXONOMY_FILE, sheet_name="MAIN")

    # Build lookup: taxonomy Item → taxonomy levels
    taxonomy['_key'] = taxonomy['Item'].astype(str).str.strip()
    level_cols = [col for col in ['Level 1', 'Level 2', 'Level 3', 'Level 4', 'Level 5'] if col in taxonomy.columns]
    tax_lookup = taxonomy.set_index('_key')[level_cols].to_dict('index')

    # Identify all SYTELINE rows (overwrite mode)
    syteline_mask = df_item_final.get('source_system', pd.Series('', index=df_item_final.index)) == "SYTELINE"
    target_mask = syteline_mask
    target_count = target_mask.sum()

    if target_count == 0:
        print("  No SYTELINE items found for taxonomy refresh.")
        return

    # Get UNIQUE item IDs that need categories
    unique_item_ids = df_item_final[target_mask]['Item_ID'].unique()
    print(f"  Applying taxonomy to {len(unique_item_ids):,} unique SYTELINE items ({target_count:,} total rows)...")

    # Build mapping: Item_ID → tax categories
    item_categories = {}
    filled = 0
    for item_id in unique_item_ids:
        raw_id = str(item_id).strip()
        lookup_key = raw_id
        tax_row = tax_lookup.get(lookup_key)
        if tax_row:
            item_categories[raw_id] = {
                'Category_Level_1': tax_row.get('Level 1', ''),
                'Category_Level_2': tax_row.get('Level 2', ''),
                'Category_Level_3': tax_row.get('Level 3', ''),
                'Category_Level_4': tax_row.get('Level 4', ''),
                'Category_Level_5': tax_row.get('Level 5', '')
            }
            filled += 1

    # Apply categories to all matching rows
    for idx in df_item_final[target_mask].index:
        item_id = str(df_item_final.at[idx, 'Item_ID']).strip()
        if item_id in item_categories:
            cats = item_categories[item_id]
            if 'Category_Level_1' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_1'] = cats['Category_Level_1']
            if 'Category_Level_2' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_2'] = cats['Category_Level_2']
            if 'Category_Level_3' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_3'] = cats['Category_Level_3']
            if 'Category_Level_4' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_4'] = cats['Category_Level_4']
            if 'Category_Level_5' in df_item_final.columns:
                df_item_final.at[idx, 'Category_Level_5'] = cats['Category_Level_5']

    print(f"  Filled categories for {filled:,} unique items ({target_count:,} total rows).")

    if filled < len(unique_item_ids):
        print(f"  Warning: {len(unique_item_ids) - filled:,} unique SYTELINE items had no match in taxonomy.")



def refresh_mappings():
    """
    Refreshes the vendor and item mapping tables with new entries from staging data.
    Uses new snake_case column naming convention.
    """
    print("\nRefreshing mappings...")

    # 1. Load Staging Data
    if not os.path.exists(STAGING_FILE):
        print(f"Error: Staging file not found at {STAGING_FILE}")
        return

    # Keep literal placeholders like 'N/A' as strings instead of auto-converting to NaN.
    df_staging = pd.read_csv(STAGING_FILE, low_memory=False, keep_default_na=False)
    print(f"Loaded {len(df_staging):,} rows from staging.")

    # --- Vendor Mappings ---
    print("\nProcessing Vendor Mappings...")
    df_vendor_map = load_csv(VENDOR_MAP_FILE)
    if df_vendor_map is not None:
        df_vendor_map = sanitize_vendor_map_rows(df_vendor_map, 'existing vendor_map.csv')

    # Get cleaned unique vendors from staging.
    if 'vendor_name' in df_staging.columns:
        df_vendor_staging = df_staging[['vendor_name']].copy()
        df_vendor_staging['vendor_name'] = df_vendor_staging['vendor_name'].astype(str).str.strip()
        blank_vendor_mask = df_vendor_staging['vendor_name'].str.lower().isin(['', 'nan', 'none', 'n/a'])
        blank_vendor_count = blank_vendor_mask.sum()
        if blank_vendor_count > 0:
            print(f"Skipped {blank_vendor_count:,} blank vendor rows from staging.")
        df_vendor_staging = df_vendor_staging[~blank_vendor_mask].copy()

        staging_vendors = df_vendor_staging['vendor_name'].drop_duplicates().tolist()
    else:
        print("Warning: No 'vendor_name' column in staging.")
        staging_vendors = []

    if df_vendor_map is None or df_vendor_map.empty:
        # Create new
        existing_vendors = set()
        df_existing = pd.DataFrame(columns=['Raw_Name', 'Standardized_Name'])
    else:
        existing_vendors = set(df_vendor_map['Raw_Name'].astype(str))
        df_existing = df_vendor_map

    # Identify new vendors
    new_vendors = [v for v in staging_vendors if str(v) not in existing_vendors]

    if new_vendors:
        print(f"Found {len(new_vendors)} new vendors.")
        df_new = pd.DataFrame({'Raw_Name': new_vendors, 'Standardized_Name': ''})

        # Add other columns if they exist in existing map
        for col in df_existing.columns:
            if col not in df_new.columns:
                df_new[col] = ''

        # Concatenate: New on TOP
        df_vendor_final = pd.concat([df_new, df_existing], ignore_index=True)
    else:
        print("No new vendors found.")
        df_vendor_final = df_existing

    df_vendor_final = sanitize_vendor_map_rows(df_vendor_final, 'refreshed vendor_map dataframe')

    # Save Vendor Map
    os.makedirs(os.path.dirname(VENDOR_MAP_FILE), exist_ok=True)
    df_vendor_final.to_csv(VENDOR_MAP_FILE, index=False)
    print(f"Saved {len(df_vendor_final):,} vendors to {VENDOR_MAP_FILE}")

    # --- Item Mappings ---
    print("\nProcessing Item Mappings...")
    df_item_map = load_csv(ITEM_MAP_FILE)
    if df_item_map is not None:
        df_item_map = sanitize_item_map_columns(df_item_map, 'existing item_map.csv')


    # Get unique items from staging with best description
    if 'item_id' not in df_staging.columns:
        print("Warning: No 'item_id' column in staging.")
        df_staging_items = pd.DataFrame()
    else:
        # Columns to use for description extraction (line_description is fallback for Epicor)
        desc_cols = ['item_id', 'item_description', 'item_display_name', 'item_name_mpn', 'line_description']
        available_cols = [c for c in desc_cols if c in df_staging.columns]

        # Group by item_id and get best description + source_system for each
        print("Extracting best descriptions for each item...")
        df_subset = df_staging[available_cols].copy()
        df_subset['item_id'] = df_subset['item_id'].apply(normalize_item_id)
        df_staging['item_id'] = df_staging['item_id'].apply(normalize_item_id)

        # Capture source_system per item_id (take first occurrence)
        item_source_systems = {}
        if 'source_system' in df_staging.columns:
            for item_id, group in df_staging.groupby('item_id'):
                item_source_systems[str(item_id)] = group['source_system'].iloc[0]

        # Get best description for each item
        item_descriptions = {}
        for item_id, group in df_subset.groupby('item_id'):
            # print(f"  Best description for {item_id}: {item_descriptions[item_id]}")
            item_descriptions[item_id] = get_best_description(group)
           
        df_staging_items = pd.DataFrame({
            'item_id': list(item_descriptions.keys()),
            'item_description': list(item_descriptions.values())
        })
        df_staging_items['source_system'] = df_staging_items['item_id'].map(item_source_systems).fillna('')
        print(f"Found {len(df_staging_items):,} unique items in staging.")
        
        # Show breakdown by source system
        if 'source_system' in df_staging_items.columns:
            print("\n  Unique items by source system:")
            for source in df_staging_items['source_system'].unique():
                count = (df_staging_items['source_system'] == source).sum()
                print(f"    {source if source else 'UNKNOWN'}: {count:,}")

    if df_item_map is None or df_item_map.empty:
        existing_items = set()
        df_existing_items = pd.DataFrame(columns=['Item_ID', 'Raw_Description', 'Category', 'Sub_Category'])
    else:
        df_item_map['Item_ID'] = df_item_map['Item_ID'].apply(normalize_item_id)
        existing_items = set(df_item_map['Item_ID'].astype(str))
        df_existing_items = df_item_map

    if not df_staging_items.empty:
        # Filter for items NOT in existing
        df_new_items = df_staging_items[~df_staging_items['item_id'].isin(existing_items)].copy()

        if not df_new_items.empty:
            print(f"Found {len(df_new_items):,} new items to add.")

            # Prepare DataFrame - map to existing column names in item_map
            df_new_items = df_new_items.rename(columns={
                'item_id': 'Item_ID',
                'item_description': 'Raw_Description'
            })

            # Ensure required columns exist
            if 'Raw_Description' not in df_new_items.columns:
                df_new_items['Raw_Description'] = ''
            df_new_items['Category'] = ''
            df_new_items['Sub_Category'] = ''

            # Select only relevant columns (include source_system)
            df_new_items = df_new_items[['Item_ID', 'Raw_Description', 'Category', 'Sub_Category', 'source_system']]

            # Concatenate: New on TOP
            df_item_final = pd.concat([df_new_items, df_existing_items], ignore_index=True)

        else:
            print("No new items found.")
            df_item_final = df_existing_items

        # Also update existing items with empty or unhelpful descriptions
        # (includes items where Raw_Description equals Item_ID)
        empty_desc_mask = (
            df_item_final['Raw_Description'].isna() |
            (df_item_final['Raw_Description'] == '') |
            (df_item_final['Raw_Description'] == '[FILL IN DESCRIPTION]') |
            (df_item_final['Raw_Description'].astype(str) == df_item_final['Item_ID'].astype(str))
        )
        items_to_update = df_item_final[empty_desc_mask]['Item_ID'].astype(str)

        updated_count = 0
        for idx in df_item_final[empty_desc_mask].index:
            item_id = str(df_item_final.at[idx, 'Item_ID'])
            if item_id in item_descriptions and item_descriptions[item_id]:
                df_item_final.at[idx, 'Raw_Description'] = item_descriptions[item_id]
                updated_count += 1

        if updated_count > 0:
            print(f"Updated {updated_count:,} existing items with better descriptions.")
    else:
        print("No item data in staging.")
        df_item_final = df_existing_items

    # Backfill source_system for existing items that don't have it yet
    if 'source_system' not in df_item_final.columns:
        df_item_final['source_system'] = ''
    df_item_final['Item_ID'] = df_item_final['Item_ID'].apply(normalize_item_id)
    df_item_final['source_system'] = df_item_final['source_system'].astype(str).str.strip()
    missing_source = df_item_final['source_system'].isna() | (df_item_final['source_system'] == '')
    if missing_source.any() and item_source_systems:
        df_item_final.loc[missing_source, 'source_system'] = (
            df_item_final.loc[missing_source, 'Item_ID']
            .astype(str)
            .map(item_source_systems)
            .fillna('')
        )

    # Count remaining empty or unhelpful descriptions
    empty_count = (
        df_item_final['Raw_Description'].isna() |
        (df_item_final['Raw_Description'] == '') |
        (df_item_final['Raw_Description'] == '[FILL IN DESCRIPTION]') |
        (df_item_final['Raw_Description'].astype(str) == df_item_final['Item_ID'].astype(str))
    ).sum()
    print(f"Remaining items with empty/unhelpful descriptions: {empty_count:,}")

    # --- Apply VanTran Taxonomy Categories ---
    print("\nApplying VanTran taxonomy categories...")
    for col in ['Category_Level_1', 'Category_Level_2', 'Category_Level_3', 'Category_Level_4', 'Category_Level_5']:
        if col not in df_item_final.columns:
            df_item_final[col] = ''
    _apply_vantran_taxonomy(df_item_final)
    _apply_syteline_taxonomy(df_item_final)

    # Final dedup guardrail: keep one best row per Item_ID + source_system.
    # This prevents deleted duplicates from reappearing on subsequent refresh runs.
    if 'source_system' not in df_item_final.columns:
        df_item_final['source_system'] = ''
    df_item_final['_desc_score'] = df_item_final.apply(
        lambda r: description_quality(r.get('Raw_Description'), r.get('Item_ID')),
        axis=1
    )
    before_dedup = len(df_item_final)
    df_item_final = (
        df_item_final
        .sort_values(['_desc_score'], ascending=False)
        .drop_duplicates(subset=['Item_ID', 'source_system'], keep='first')
        .drop(columns=['_desc_score'])
        .reset_index(drop=True)
    )
    removed = before_dedup - len(df_item_final)
    if removed > 0:
        print(f"Removed {removed:,} duplicate Item_ID/source_system rows from item_map.")

    # Hard schema guard before save: strip any accidental duplicate/mangled headers.
    df_item_final = sanitize_item_map_columns(df_item_final, 'refreshed item_map dataframe')

    # Save Item Map
    df_item_final.to_csv(ITEM_MAP_FILE, index=False)
    print(f"Saved {len(df_item_final):,} items to {ITEM_MAP_FILE}")


if __name__ == "__main__":
    refresh_mappings()
