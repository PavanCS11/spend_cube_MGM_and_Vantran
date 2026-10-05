import pandas as pd
import yaml
import os
import glob
import re
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from .config_loader import ConfigLoader


class Normalizer:
    """
    CSV-driven normalizer that reads field mappings from transaction_field_mapping.csv
    and outputs a single combined normalized file.
    """

    def __init__(self, config_path: str, schema_dir: str, input_dir: str, output_dir: str):
        self.config_loader = ConfigLoader(config_path)
        self.schema_dir = schema_dir
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.config_dir = os.path.dirname(config_path)

        # Load the CSV field mapping
        self.field_mapping = self._load_field_mapping()

        # Load schema for type information
        self.schema_types = self._load_schema_types()

        # Get target field names from the CSV mapping
        self.target_fields = self.field_mapping['Field Name'].tolist()

    def _load_field_mapping(self) -> pd.DataFrame:
        """Loads the transaction_field_mapping.csv as the authoritative mapping source."""
        mapping_file = self.config_loader.config.get('field_mapping_file', 'transaction_field_mapping.csv')
        mapping_path = os.path.join(self.config_dir, mapping_file)

        if not os.path.exists(mapping_path):
            raise FileNotFoundError(f"Field mapping file not found: {mapping_path}")

        df = pd.read_csv(mapping_path, encoding='utf-8-sig')  # Handle BOM
        print(f"Loaded field mapping with {len(df)} fields")
        return df

    def _load_schema_types(self) -> Dict[str, str]:
        """Loads type information from the transactions schema."""
        schema_path = os.path.join(self.schema_dir, 'transactions.yaml')
        if not os.path.exists(schema_path):
            print(f"Warning: Schema file not found at {schema_path}")
            return {}

        with open(schema_path, 'r') as f:
            schema_def = yaml.safe_load(f)
            return {field['name']: field.get('type', 'string')
                    for field in schema_def.get('fields', [])}

    def _extract_file_date(self, filename: str) -> Optional[datetime]:
        """Extracts date from filename pattern like '121025' (MMDDYY)."""
        # Look for 6-digit date pattern (MMDDYY)
        match = re.search(r'(\d{6})', filename)
        if match:
            date_str = match.group(1)
            try:
                # Parse MMDDYY format
                return datetime.strptime(date_str, '%m%d%y')
            except ValueError:
                pass
        return None

    def _print_data_freshness_report(self, combined_df: pd.DataFrame, file_dates: Dict[str, datetime]):
        """Prints data freshness and date range validation report."""
        print("\n" + "="*60)
        print("DATA FRESHNESS & RANGE VALIDATION")
        print("="*60)

        today = datetime.now()

        # Report file dates
        if file_dates:
            print("\nSource File Dates:")
            for filename, file_date in sorted(file_dates.items()):
                days_old = (today - file_date).days
                status = "STALE" if days_old > 7 else "OK"
                print(f"  {filename}: {file_date.strftime('%Y-%m-%d')} ({days_old} days old) [{status}]")

        # Analyze order_date by source system
        if 'order_date' in combined_df.columns and 'source_system' in combined_df.columns:
            print("\nOrder Date Ranges by Source:")
            combined_df['order_date_parsed'] = pd.to_datetime(combined_df['order_date'], errors='coerce')

            for source in combined_df['source_system'].dropna().unique():
                source_data = combined_df[combined_df['source_system'] == source]
                dates = source_data['order_date_parsed'].dropna()

                if not dates.empty:
                    min_date = dates.min()
                    max_date = dates.max()
                    days_since_newest = (today - max_date).days if pd.notna(max_date) else None

                    print(f"\n  {source}:")
                    print(f"    Earliest order: {min_date.strftime('%Y-%m-%d') if pd.notna(min_date) else 'N/A'}")
                    print(f"    Latest order:   {max_date.strftime('%Y-%m-%d') if pd.notna(max_date) else 'N/A'}")
                    print(f"    Row count:      {len(source_data):,}")

                    if days_since_newest and days_since_newest > 7:
                        print(f"    WARNING: Most recent order is {days_since_newest} days old!")

            # Clean up temp column
            combined_df.drop(columns=['order_date_parsed'], inplace=True)

        # Check for null dates
        if 'order_date' in combined_df.columns:
            null_count = combined_df['order_date'].isna().sum()
            null_pct = (null_count / len(combined_df)) * 100
            if null_pct > 5:
                print(f"\nWARNING: {null_pct:.1f}% of records have missing order_date ({null_count:,} rows)")

        print("\n" + "="*60)

    def _write_pipeline_metadata(self, file_dates: Dict[str, datetime]):
        """Writes pipeline metadata including max file date for downstream steps."""
        if not file_dates:
            print("  Warning: No file dates available for metadata")
            return

        max_file_date = max(file_dates.values())

        metadata = {
            "max_file_date": max_file_date.strftime('%Y-%m-%d'),
            "file_dates": {k: v.strftime('%Y-%m-%d') for k, v in file_dates.items()},
            "generated_at": datetime.now().isoformat()
        }

        metadata_path = os.path.join(self.output_dir, "pipeline_metadata.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        print(f"  Pipeline metadata saved: max_file_date = {max_file_date.strftime('%Y-%m-%d')}")

    @staticmethod
    def _norm_line(series: pd.Series) -> pd.Series:
        """Normalises a PO line identifier to a clean integer string ('3', not '3.0')."""
        return pd.to_numeric(series, errors='coerce').astype('Int64').astype(str)

    @staticmethod
    def _normalize_syteline_key(series: pd.Series) -> pd.Series:
        """
        Normalize Syteline join-key columns while preserving alphanumeric values.

        Examples:
            12345      -> '12345'
            12345.0    -> '12345'
            ' 12345 '  -> '12345'
            'ABC123'   -> 'ABC123'
            blank/NaN  -> ''
        """
        if series is None:
            return pd.Series(dtype='object')

        normalized = (
            series
            .astype('string')
            .str.replace('\u00a0', ' ', regex=False)
            .str.strip()
        )

        numeric_mask = normalized.str.fullmatch(r'\d+\.0+', na=False)

        normalized.loc[numeric_mask] = (
            normalized.loc[numeric_mask]
            .str.replace(r'\.0+$', '', regex=True)
        )

        return normalized.fillna('')


    @staticmethod
    def _is_missing_syteline_value(series: pd.Series) -> pd.Series:
        """
        Identify values that should be treated as missing for Syteline
        backfill purposes.
        """
        if series is None:
            return pd.Series(dtype=bool)

        normalized = (
            series
            .astype('string')
            .str.strip()
            .str.lower()
        )

        return (
            series.isna()
            | normalized.isin({
                '',
                'nan',
                'none',
                'null',
                'n/a',
                '<na>',
            })
        )


    @staticmethod
    def _first_non_missing(series: pd.Series):
        """
        Return the first non-missing value from a Series.
        """
        valid = series[
            ~Normalizer._is_missing_syteline_value(series)
        ]

        if valid.empty:
            return None

        return valid.iloc[0]


    def _load_syteline_backfill_file(self) -> pd.DataFrame:
        """
        Load the Syteline Backfill Missing Lines file.

        This file is a lookup/enrichment source only and must never be
        appended to the transaction dataset.
        """
        pattern = os.path.join(
            self.input_dir,
            'Syteline/Syteline Backfill Missing Lines*.xlsx'
        )

        files = glob.glob(pattern)

        if not files:
            print(
                "\n  Syteline backfill: no "
                "'Syteline Backfill Missing Lines*.xlsx' file found. "
                "Skipping backfill."
            )
            return pd.DataFrame()

        files.sort()

        print(
            f"\n  Loading Syteline backfill lookup from "
            f"{len(files)} file(s)..."
        )

        frames = []

        required_columns = {
            'PO_Number',
            'Line_ID',
            'Document_Number',
            'Vendor_ID',
            'Vendor_Name',
            'Promise Date',
            'Order_Date',
            'Recv_Date',
        }

        for file_path in files:
            filename = os.path.basename(file_path)

            try:
                df = pd.read_excel(
                    file_path,
                    dtype=object
                )

                print(
                    f"    {filename}: "
                    f"{len(df):,} rows, "
                    f"{len(df.columns):,} columns"
                )

                missing_columns = (
                    required_columns - set(df.columns)
                )

                if missing_columns:
                    raise ValueError(
                        f"Syteline backfill file '{filename}' "
                        f"is missing required columns: "
                        f"{sorted(missing_columns)}"
                    )

                frames.append(
                    df[
                        [
                            'PO_Number',
                            'Line_ID',
                            'Document_Number',
                            'Vendor_ID',
                            'Vendor_Name',
                            'Promise Date',
                            'Order_Date',
                            'Recv_Date',
                        ]
                    ].copy()
                )

            except Exception as exc:
                raise ValueError(
                    f"Failed to load Syteline backfill file "
                    f"'{filename}': {exc}"
                ) from exc

        if not frames:
            return pd.DataFrame()

        backfill = pd.concat(
            frames,
            ignore_index=True
        )

        print(
            f"    Total Syteline backfill rows loaded: "
            f"{len(backfill):,}"
        )

        return backfill


    def _build_syteline_receipt_backfill_lookup(
        self,
        backfill: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Build a receipt-level Syteline backfill lookup.

        Key:
            PO_Number + Line_ID + Document_Number

        Vendor_ID / Vendor_Name:
            First non-missing value.

        Promise Date:
            First non-missing value.
        """
        if backfill.empty:
            return pd.DataFrame()

        lookup = backfill.copy()

        lookup['_key_po'] = self._normalize_syteline_key(
            lookup['PO_Number']
        )

        lookup['_key_line'] = self._normalize_syteline_key(
            lookup['Line_ID']
        )

        lookup['_key_document'] = self._normalize_syteline_key(
            lookup['Document_Number']
        )

        valid_key_mask = (
            lookup['_key_po'].ne('') &
            lookup['_key_line'].ne('') &
            lookup['_key_document'].ne('')
        )

        lookup = lookup.loc[
            valid_key_mask,
            [
                '_key_po',
                '_key_line',
                '_key_document',
                'Vendor_ID',
                'Vendor_Name',
                'Promise Date',
                'Order_Date',
                'Recv_Date',
            ]
        ].copy()

        if lookup.empty:
            print(
                "    Syteline receipt backfill: "
                "no valid primary keys found."
            )
            return pd.DataFrame()

        lookup = (
            lookup
            .groupby(
                [
                    '_key_po',
                    '_key_line',
                    '_key_document',
                ],
                as_index=False,
                sort=False,
            )
            .agg(
                {
                    'Vendor_ID': self._first_non_missing,
                    'Vendor_Name': self._first_non_missing,
                    'Promise Date': self._first_non_missing,
                    'Order_Date': self._first_non_missing,
                    'Recv_Date': self._first_non_missing,
                }
            )
        )

        lookup['Promise Date'] = pd.to_datetime(
            lookup['Promise Date'],
            errors='coerce'
        ).dt.strftime('%Y-%m-%d')

        lookup['Order_Date'] = pd.to_datetime(
            lookup['Order_Date'],
            errors='coerce'
        ).dt.strftime('%Y-%m-%d')

        lookup['Recv_Date'] = pd.to_datetime(
            lookup['Recv_Date'],
            errors='coerce'
        ).dt.strftime('%Y-%m-%d')

        print(
            f"    Receipt backfill lookup: "
            f"{len(lookup):,} unique "
            f"PO+Line+Document keys"
        )

        return lookup


    def _build_syteline_open_po_backfill_lookup(
        self,
        backfill: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Build an Open PO-level Syteline backfill lookup.

        Key:
            PO_Number + Line_ID

        Vendor_ID / Vendor_Name:
            First non-missing value.

        Promise Date:
            MAX(Promise Date).
        """
        if backfill.empty:
            return pd.DataFrame()

        lookup = backfill.copy()

        lookup['_key_po'] = self._normalize_syteline_key(
            lookup['PO_Number']
        )

        lookup['_key_line'] = self._normalize_syteline_key(
            lookup['Line_ID']
        )

        valid_key_mask = (
            lookup['_key_po'].ne('') &
            lookup['_key_line'].ne('')
        )

        lookup = lookup.loc[
            valid_key_mask,
            [
                '_key_po',
                '_key_line',
                'Vendor_ID',
                'Vendor_Name',
                'Promise Date',
                'Order_Date',
            ]
        ].copy()

        if lookup.empty:
            print(
                "    Syteline Open PO backfill: "
                "no valid primary keys found."
            )
            return pd.DataFrame()

        lookup['_promise_date_parsed'] = pd.to_datetime(
            lookup['Promise Date'],
            errors='coerce'
        )

        lookup['_order_date_parsed'] = pd.to_datetime(
            lookup['Order_Date'],
            errors='coerce'
        )
        
        grouped = (
            lookup
            .groupby(
                [
                    '_key_po',
                    '_key_line',
                ],
                as_index=False,
                sort=False
            )
            .agg(
                Vendor_ID=(
                    'Vendor_ID',
                    self._first_non_missing
                ),
                Vendor_Name=(
                    'Vendor_Name',
                    self._first_non_missing
                ),
                _promise_date_parsed=(
                    '_promise_date_parsed',
                    'max'
                ),
                _order_date_parsed=(
                    '_order_date_parsed',
                    'max'
                ),
            )
        )

        grouped['Promise Date'] = (
            grouped['_promise_date_parsed']
            .dt.strftime('%Y-%m-%d')
        )

        grouped['Order_Date'] = (
            grouped['_order_date_parsed']
            .dt.strftime('%Y-%m-%d')
        )

        grouped.drop(
            columns=['_promise_date_parsed', '_order_date_parsed'],
            inplace=True
        )

        print(
            f"    Open PO backfill lookup: "
            f"{len(grouped):,} unique PO+Line keys"
        )

        return grouped


    def _backfill_syteline_missing_fields(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Backfill missing Syteline fields from the
        Syteline Backfill Missing Lines file.

        Receipts:
            po_number + receipt_line + receipt_number
            =
            PO_Number + Line_ID + Document_Number

        Open POs:
            po_number + po_line
            =
            PO_Number + Line_ID

        Existing non-missing values are never overwritten.
        """
        if df.empty:
            return df

        required_columns = {
            'source_system',
            'transaction_type',
            'po_number',
            'vendor_id',
            'vendor_name',
            'promise_date',
            'order_date',
            'receipt_date',
        }

        missing_columns = required_columns - set(df.columns)

        if missing_columns:
            raise ValueError(
                "Cannot perform Syteline backfill. "
                f"Normalized data is missing columns: "
                f"{sorted(missing_columns)}"
            )

        # Backfill values may be strings even when the existing normalized
        # column was inferred as numeric (for example vendor_id as float64).
        # Use object dtype so existing values are preserved and missing
        # values can safely be populated from the Syteline lookup.
        for column in [
            'vendor_id',
            'vendor_name',
            'promise_date',
            'order_date',
            'receipt_date'
        ]:
            df[column] = df[column].astype('object')

        syteline_mask = (
            df['source_system']
            .astype(str)
            .str.upper()
            .str.strip()
            .eq('SYTELINE')
        )

        if not syteline_mask.any():
            return df

        backfill = self._load_syteline_backfill_file()

        if backfill.empty:
            return df

        # ============================================================
        # SYTELINE RECEIPTS
        # ============================================================
        receipt_mask = (
            syteline_mask &
            df['transaction_type']
            .astype(str)
            .str.upper()
            .str.strip()
            .isin({'RECEIPT', 'RECEIPTS'})
        )

        if receipt_mask.any():
            required_receipt_columns = {
                'receipt_line',
                'receipt_number',
            }

            missing_receipt_columns = (
                required_receipt_columns - set(df.columns)
            )

            if missing_receipt_columns:
                raise ValueError(
                    "Cannot perform Syteline receipt backfill. "
                    f"Missing normalized columns: "
                    f"{sorted(missing_receipt_columns)}"
                )

            receipt_lookup = (
                self._build_syteline_receipt_backfill_lookup(
                    backfill
                )
            )

            if not receipt_lookup.empty:
                receipt_rows = df.loc[
                    receipt_mask,
                    [
                        'po_number',
                        'receipt_line',
                        'receipt_number',
                        'vendor_id',
                        'vendor_name',
                        'promise_date',
                        'order_date',
                        'receipt_date',
                    ],
                ].copy()

                # Preserve the original DataFrame index because merge()
                # creates a new index.
                receipt_rows['_original_index'] = (
                    receipt_rows.index
                )

                receipt_rows['_key_po'] = (
                    self._normalize_syteline_key(
                        receipt_rows['po_number']
                    )
                )

                receipt_rows['_key_line'] = (
                    self._normalize_syteline_key(
                        receipt_rows['receipt_line']
                    )
                )

                receipt_rows['_key_document'] = (
                    self._normalize_syteline_key(
                        receipt_rows['receipt_number']
                    )
                )

                receipt_rows = receipt_rows.merge(
                    receipt_lookup.rename(
                        columns={
                            'Vendor_ID': '_bf_vendor_id',
                            'Vendor_Name': '_bf_vendor_name',
                            'Promise Date': '_bf_promise_date',
                            'Order_Date': '_bf_order_date',
                            'Recv_Date': '_bf_receipt_date',
                        }
                    ),
                    on=[
                        '_key_po',
                        '_key_line',
                        '_key_document',
                    ],
                    how='left',
                    validate='many_to_one',
                )

                for target, source in [
                    ('vendor_id', '_bf_vendor_id'),
                    ('vendor_name', '_bf_vendor_name'),
                    ('promise_date', '_bf_promise_date'),
                    ('order_date', '_bf_order_date'),
                    ('receipt_date', '_bf_receipt_date'),
                ]:
                    target_missing = (
                        self._is_missing_syteline_value(
                            receipt_rows[target]
                        )
                    )

                    source_available = (
                        ~self._is_missing_syteline_value(
                            receipt_rows[source]
                        )
                    )

                    fill_mask = (
                        target_missing &
                        source_available
                    )

                    if fill_mask.any():
                        original_indices = (
                            receipt_rows.loc[
                                fill_mask,
                                '_original_index'
                            ]
                        )

                        df.loc[
                            original_indices,
                            target
                        ] = receipt_rows.loc[
                            fill_mask,
                            source
                        ].values

                        print(
                            f"    Syteline receipts {target} "
                            f"backfilled: "
                            f"{fill_mask.sum():,} rows"
                        )

        # ============================================================
        # SYTELINE OPEN POs
        # ============================================================
        open_mask = (
            syteline_mask &
            df['transaction_type']
            .astype(str)
            .str.upper()
            .str.strip()
            .isin({'OPEN_ORDER', 'OPEN ORDERS'})
        )

        if open_mask.any():
            open_lookup = (
                self._build_syteline_open_po_backfill_lookup(
                    backfill
                )
            )

            if not open_lookup.empty:
                open_rows = df.loc[
                    open_mask,
                    [
                        'po_number',
                        'po_line',
                        'vendor_id',
                        'vendor_name',
                        'promise_date',
                        'order_date',
                    ],
                ].copy()

                # Preserve original DataFrame index because merge()
                # creates a new index.
                open_rows['_original_index'] = (
                    open_rows.index
                )

                open_rows['_key_po'] = (
                    self._normalize_syteline_key(
                        open_rows['po_number']
                    )
                )

                open_rows['_key_line'] = (
                    self._normalize_syteline_key(
                        open_rows['po_line']
                    )
                )

                open_rows = open_rows.merge(
                    open_lookup.rename(
                        columns={
                            'Vendor_ID': '_bf_vendor_id',
                            'Vendor_Name': '_bf_vendor_name',
                            'Promise Date': '_bf_promise_date',
                            'Order_Date': '_bf_order_date',
                        }
                    ),
                    on=[
                        '_key_po',
                        '_key_line',
                    ],
                    how='left',
                    validate='many_to_one',
                )

                for target, source in [
                    ('vendor_id', '_bf_vendor_id'),
                    ('vendor_name', '_bf_vendor_name'),
                    ('promise_date', '_bf_promise_date'),
                    ('order_date', '_bf_order_date'),
                ]:
                    target_missing = (
                        self._is_missing_syteline_value(
                            open_rows[target]
                        )
                    )

                    source_available = (
                        ~self._is_missing_syteline_value(
                            open_rows[source]
                        )
                    )

                    fill_mask = (
                        target_missing &
                        source_available
                    )

                    if fill_mask.any():
                        original_indices = (
                            open_rows.loc[
                                fill_mask,
                                '_original_index'
                            ]
                        )

                        df.loc[
                            original_indices,
                            target
                        ] = open_rows.loc[
                            fill_mask,
                            source
                        ].values

                        print(
                            f"    Syteline open POs {target} "
                            f"backfilled: "
                            f"{fill_mask.sum():,} rows"
                        )

        return df

    def _load_po_line_dates_lookup(self) -> pd.DataFrame:
        """Loads NS PO Line Dates and returns a LINE-LEVEL lookup for joining to NS Receipt rows.

        Key: (PO Number, PO Line ID). One row per PO line — no aggregation.
        """

        pattern = os.path.join(
            self.input_dir,
            'Netsuite/Netsuite PO Line Dates*.csv'
        )

        files = glob.glob(pattern)

        if not files:
            print(
                "  Warning: No NS PO Line Dates file found — "
                "NS receipt date fields will be NULL"
            )
            return pd.DataFrame()

        files.sort(
            key=os.path.getmtime,
            reverse=True
        )

        file_path = files[0]

        print(
            f"\n  Loading PO Line Dates lookup from: "
            f"{os.path.basename(file_path)}"
        )

        df = pd.read_csv(
            file_path,
            encoding='utf-8-sig',
            low_memory=False
        )

        po_num_col = 'PO Number'
        po_line_col = 'PO Line ID'

        source_cols = {
            'promise_date': 'Maximum of PO New Promise Date',
            'old_promise_date': 'Maximum of PO Promise Date',
            'due_date': 'Maximum of PO Due Date',
            'requested_date': 'Maximum of Requested Date',
            'order_date': 'Maximum of PO Date',
        }

        for required in (po_num_col, po_line_col):
            if required not in df.columns:
                print(
                    f"  Warning: PO Line Dates missing "
                    f"'{required}' column — skipping join"
                )
                return pd.DataFrame()

        lookup = pd.DataFrame({
            '_key_po': df[po_num_col].astype(str).str.strip(),
            '_key_line': self._norm_line(df[po_line_col]),
        })

        for target, src in source_cols.items():

            if src in df.columns:
                lookup[target] = (
                    pd.to_datetime(
                        df[src],
                        errors='coerce'
                    )
                    .dt.strftime('%Y-%m-%d')
                )
            else:
                print(
                    f"  Warning: PO Line Dates missing '{src}' — "
                    f"{target} will be NULL on NS receipts"
                )
                lookup[target] = None

        # The lookup must be unique at PO + line grain.
        dupes = lookup.duplicated(
            ['_key_po', '_key_line']
        ).sum()

        if dupes:
            raise ValueError(
                f"PO Line Dates is not unique on PO Number + PO Line ID "
                f"({dupes:,} duplicate keys). "
                "Refusing to aggregate. Check the saved search grouping."
            )

        print(
            f"  PO Line Dates lookup: "
            f"{len(lookup):,} PO lines across "
            f"{lookup['_key_po'].nunique():,} POs"
        )

        return lookup

    def _join_po_line_dates(self, df: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
        """Joins PO Line Dates onto NS RECEIPT rows at PO LINE grain.

        Populates promise_date, old_promise_date, due_date,
        requested_date and order_date.

        Join key:
            po_number + po_line
        """

        if lookup is None or lookup.empty:
            return df

        ns_receipt_mask = (
            (df['source_system'] == 'NETSUITE') &
            (df['transaction_type'] == 'RECEIPT')
        )

        total = int(ns_receipt_mask.sum())

        if total == 0:
            return df

        print(
            f"\n  Joining PO Line Dates onto "
            f"{total:,} NS Receipt rows at PO+line grain..."
        )

        date_cols = [
            'promise_date',
            'old_promise_date',
            'due_date',
            'requested_date',
            'order_date'
        ]

        for col in date_cols:
            if col not in df.columns:
                df[col] = None

        if (
            'po_line' not in df.columns or
            df.loc[ns_receipt_mask, 'po_line'].isna().all()
        ):
            print(
                "  Warning: po_line is empty on NS receipts — "
                "check that transaction_field_mapping.csv maps "
                "po_line to 'PO Line ID' for NS Receipts. "
                "Skipping join."
            )
            return df

        ns_receipts = df.loc[
            ns_receipt_mask,
            ['po_number', 'po_line']
        ].copy()

        ns_receipts['_key_po'] = (
            ns_receipts['po_number']
            .astype(str)
            .str.strip()
        )

        ns_receipts['_key_line'] = self._norm_line(
            ns_receipts['po_line']
        )

        rows_before = len(ns_receipts)

        merged = ns_receipts.merge(
            lookup.rename(
                columns={
                    c: f'_j_{c}'
                    for c in date_cols
                }
            ),
            on=['_key_po', '_key_line'],
            how='left'
        )

        if len(merged) != rows_before:
            raise ValueError(
                f"Join fan-out: {rows_before:,} receipt rows "
                f"became {len(merged):,}. "
                "Lookup is not unique on PO+line."
            )

        for col in date_cols:
            df.loc[
                ns_receipt_mask,
                col
            ] = merged[
                f'_j_{col}'
            ].values

        matched = int(
            merged[
                [f'_j_{c}' for c in date_cols]
            ]
            .notna()
            .any(axis=1)
            .sum()
        )

        print(
            f"    matched at PO+line: "
            f"{matched:,} / {total:,} "
            f"({matched / total * 100:.1f}%)"
        )

        for col in date_cols:
            n = int(
                merged[f'_j_{col}']
                .notna()
                .sum()
            )

            print(
                f"    {col:16s} populated: "
                f"{n:,} / {total:,} "
                f"({n / total * 100:.1f}%)"
            )

        if matched / total < 0.95:
            print(
                "  WARNING: line-level match rate below 95% — "
                "expected ~99.5%. Check po_line mapping and "
                "PO Line ID numbering before trusting NS receipt dates."
            )

        return df

    def _apply_ns_receipt_promise_fallback(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fallback: for NS receipt rows with null promise_date after the PO Line Dates join,
        pull promise_date from the NS Open POs file keyed on po_number only.

        This recovers rows (e.g. PwrQ) whose item_name_mpn didn't match the line-level
        join key. Uses the minimum Expected Receipt Date per PO as a conservative estimate.
        """
        ns_receipt_null_mask = (
            (df['source_system'] == 'NETSUITE') &
            (df['transaction_type'] == 'RECEIPT') &
            (df['promise_date'].isna())
        )
        unmatched = ns_receipt_null_mask.sum()
        if unmatched == 0:
            return df

        print(f"\n  NS Receipt promise_date fallback: {unmatched:,} unmatched rows — loading NS Open POs...")

        pattern = os.path.join(self.input_dir, 'Netsuite/Netsuite Open POs*.csv')
        files = glob.glob(pattern)
        if not files:
            print("  Warning: No NS Open POs file found — fallback skipped")
            return df

        files.sort(key=os.path.getmtime, reverse=True)
        ns_open = pd.read_csv(files[0], dtype=str)

        po_col = 'PO Number'
        erd_col = 'Maximum of Expected Receipt Date'
        if po_col not in ns_open.columns or erd_col not in ns_open.columns:
            print("  Warning: NS Open POs missing required columns — fallback skipped")
            return df

        ns_open['_key_po'] = ns_open[po_col].astype(str).str.strip()
        ns_open[erd_col] = pd.to_datetime(ns_open[erd_col], errors='coerce').dt.strftime('%Y-%m-%d')

        # Take the minimum Expected Receipt Date per PO (conservative: earliest commitment)
        po_promise = (
            ns_open.dropna(subset=[erd_col])
            .groupby('_key_po')[erd_col]
            .min()
            .reset_index()
            .rename(columns={erd_col: '_fallback_promise'})
        )

        unmatched_receipts = df[ns_receipt_null_mask].copy()
        unmatched_receipts['_key_po'] = unmatched_receipts['po_number'].astype(str).str.strip()
        merged = unmatched_receipts.merge(po_promise, on='_key_po', how='left')

        df.loc[ns_receipt_null_mask, 'promise_date'] = merged['_fallback_promise'].values

        filled = merged['_fallback_promise'].notna().sum()
        print(f"    Fallback filled promise_date: {filled:,} / {unmatched:,} ({filled/unmatched*100:.1f}%)")

        return df

    
    @staticmethod
    def _normalize_vantran_po_key(value) -> str:
        """Normalize VanTran PO references for matching open orders to receipts."""
        if pd.isna(value):
            return ''

        key = str(value).strip()
        if not key:
            return ''

        # For receipt rows, prefer the text after the last '#'
        if '#' in key:
            key = key.split('#')[-1].strip()

        # Common PO formats like "PO10304" should match "10304"
        key = re.sub(r'^PO(?=\d)', '', key, flags=re.IGNORECASE)

        # Remove extra spaces and normalize case
        key = re.sub(r'\s+', '', key).upper()
        return key

    def po_status(self, df: pd.DataFrame) -> pd.DataFrame:
        """Backfill VanTran receipt po_status from matching VanTran open-order status."""
        if df.empty:
            return df

        required_cols = {'source_system', 'transaction_type', 'po_number', 'po_status'}
        if not required_cols.issubset(df.columns):
            return df

        df = df.copy()

        vantran_mask = df['source_system'].astype(str).str.upper().eq('NETSUITE_VANTRAN')
        receipt_mask = vantran_mask & df['transaction_type'].astype(str).str.upper().eq('RECEIPT')
        open_mask = vantran_mask & df['transaction_type'].astype(str).str.upper().eq('OPEN_ORDER')

        if not receipt_mask.any() or not open_mask.any():
            return df

        # Build a matching key from open-order document number.
        df['_vantran_po_join_key'] = df['po_number'].apply(self._normalize_vantran_po_key)

        open_lookup = (
            df.loc[open_mask, ['_vantran_po_join_key', 'po_status']]
            .copy()
        )

        open_lookup['po_status'] = open_lookup['po_status'].astype(str).str.strip()
        open_lookup = open_lookup[
            open_lookup['_vantran_po_join_key'].astype(str).str.strip().ne('') &
            open_lookup['po_status'].notna() &
            (open_lookup['po_status'] != '') &
            (open_lookup['po_status'].str.lower() != 'nan')
        ]
        open_lookup = open_lookup.drop_duplicates(subset=['_vantran_po_join_key'], keep='first')

        receipt_lookup = (
            df.loc[receipt_mask, ['_vantran_po_join_key']]
            .merge(open_lookup, on='_vantran_po_join_key', how='left')
        )

        receipt_lookup['po_status'] = (
            receipt_lookup['po_status']
            .fillna('')
            .astype(str)
            .str.strip()
            .replace('', 'Completed'))
        
        df.loc[receipt_mask, 'po_status'] = receipt_lookup['po_status'].values

        matched_count = receipt_lookup['po_status'].ne('Completed').sum()
        completed_count = receipt_lookup['po_status'].eq('Completed').sum()

        print(f"  VanTran receipt po_status: {matched_count:,} rows populated "
              f"from open orders; {completed_count:,} unmatched rows marked Completed")

        df.drop(columns=['_vantran_po_join_key', '_vantran_created_by_split'], inplace=True, errors='ignore')
        return df

    def _backfill_vantran_receipt_promise_date(self, df: pd.DataFrame) -> pd.DataFrame:
        """Populate VanTran RECEIPT promise_date by joining to VanTran OPEN_ORDER.

        Join rule requested:
        - Receipt key: text after '#' from po_number (e.g., 'Purchase Order #8981' -> '8981')
        - Open key: Document Number/po_number normalized to the same key

        Only fills rows where a match is found; unmatched rows remain blank/null.
        """
        if df.empty:
            return df

        required_cols = {'source_system', 'transaction_type', 'po_number'}
        if not required_cols.issubset(df.columns):
            return df

        df = df.copy()

        vantran_mask = df['source_system'].astype(str).str.upper().eq('NETSUITE_VANTRAN')
        receipt_mask = vantran_mask & df['transaction_type'].astype(str).str.upper().eq('RECEIPT')

        if not receipt_mask.any():
            return df

        if 'promise_date' not in df.columns:
            df['promise_date'] = None

        # Only attempt backfill where receipt promise_date is currently blank/null.
        receipt_blank_promise_mask = (
            receipt_mask &
            (
                df['promise_date'].isna() |
                df['promise_date'].astype(str).str.strip().eq('') |
                df['promise_date'].astype(str).str.lower().eq('nan')
            )
        )
        if not receipt_blank_promise_mask.any():
            return df

        # Load lookup from RAW VanTran Open POs file.
        lookup = self._load_vantran_open_po_promise_lookup()
        if not lookup:
            return df

        # Build normalized keys for matching.
        receipt_lookup = df.loc[receipt_blank_promise_mask, ['po_number']].copy()
        receipt_lookup['_vantran_po_join_key'] = receipt_lookup['po_number'].apply(self._normalize_vantran_po_key)

        receipt_lookup['_raw_open_promise'] = receipt_lookup['_vantran_po_join_key'].map(lookup)

        matched = (
            receipt_lookup['_raw_open_promise'].notna() &
            receipt_lookup['_raw_open_promise'].astype(str).str.strip().ne('')
        )
        if matched.any():
            df.loc[receipt_blank_promise_mask, 'promise_date'] = receipt_lookup['_raw_open_promise'].values
            print(
                f"  VanTran receipt promise_date backfill: {matched.sum():,} "
                f"rows populated from RAW VanTran Open POs (Document Number join)"
            )

        df.drop(columns=['_vantran_po_join_key'], inplace=True, errors='ignore')
        return df

    def _load_vantran_open_po_promise_lookup(self) -> Dict[str, str]:
        """Load RAW VanTran Open POs and build Document Number -> promise_date lookup."""
        pattern = os.path.join(self.input_dir, 'Vantran/Netsuite Vantran Open POs*.xlsx')
        files = glob.glob(pattern)
        if not files:
            print("  Warning: No raw VanTran Open POs file found — promise_date backfill skipped")
            return {}

        files.sort(key=os.path.getmtime, reverse=True)
        file_path = files[0]

        try:
            raw_open = pd.read_excel(file_path, dtype=str)
        except Exception as exc:
            print(f"  Warning: Could not read raw VanTran Open POs file ({exc}) — promise_date backfill skipped")
            return {}

        doc_col = 'Document Number'
        promise_col = 'Expected Receipt Date'
        if doc_col not in raw_open.columns or promise_col not in raw_open.columns:
            print("  Warning: Raw VanTran Open POs missing Document Number/Expected Receipt Date — backfill skipped")
            return {}

        raw_open['_vantran_po_join_key'] = raw_open[doc_col].apply(self._normalize_vantran_po_key)
        raw_open[promise_col] = pd.to_datetime(raw_open[promise_col], errors='coerce').dt.strftime('%Y-%m-%d')

        valid = raw_open[
            raw_open['_vantran_po_join_key'].astype(str).str.strip().ne('') &
            raw_open[promise_col].notna() &
            raw_open[promise_col].astype(str).str.strip().ne('')
        ].copy()

        if valid.empty:
            return {}

        # Conservative approach when duplicate document numbers exist.
        grouped = valid.groupby('_vantran_po_join_key', as_index=False)[promise_col].min()
        lookup = dict(zip(grouped['_vantran_po_join_key'], grouped[promise_col]))
        print(f"  Raw VanTran Open POs lookup: {len(lookup):,} Document Number keys")
        return lookup
    

    def process_all(self):
        """Processes all configured sources and outputs a single combined file."""
        sources = self.config_loader.get_sources()
        all_normalized_data = []
        all_file_dates = {}  # Track file dates for freshness report

        for source in sources:
            df_normalized, file_dates = self.process_source(source)
            if df_normalized is not None and not df_normalized.empty:
                all_normalized_data.append(df_normalized)
                all_file_dates.update(file_dates)

        if all_normalized_data:
            # Combine all normalized data into single DataFrame
            combined_df = pd.concat(
                all_normalized_data,
                ignore_index=True,
                copy=False
            )

            # Release individual source DataFrames now that they are combined.
            del all_normalized_data

            # Join PO Line Dates onto NS Receipt rows
            # (line-level promise/due dates)
            po_line_lookup = self._load_po_line_dates_lookup()

            combined_df = self._join_po_line_dates(
                combined_df,
                po_line_lookup
            )

            # Backfill missing Syteline fields from the
            # Syteline Backfill Missing Lines file.
            #
            # IMPORTANT:
            # The backfill file is used only as a lookup.
            # It is NOT added as transaction rows.
            combined_df = self._backfill_syteline_missing_fields(
                combined_df
            )

            # Backfill VanTran receipt po_status from
            # matching VanTran open orders
            combined_df = self.po_status(combined_df)

            # Backfill VanTran receipt promise_date from
            # VanTran open-order Document Number
            combined_df = self._backfill_vantran_receipt_promise_date(
                combined_df
            )

            # Print data freshness report
            self._print_data_freshness_report(combined_df, all_file_dates)

            # Write pipeline metadata for downstream steps
            self._write_pipeline_metadata(all_file_dates)

            # Output single combined file
            output_path = os.path.join(self.output_dir, "all_transactions_normalized.csv")
            combined_df.to_csv(output_path, index=False)
            print(f"\nSaved combined normalized data to: {output_path}")
            print(f"Total rows: {len(combined_df):,}")
            print(f"Total columns: {len(combined_df.columns)}")
        else:
            print("No data was processed from any source.")

    def process_source(self, source_config: Dict[str, Any]) -> Tuple[Optional[pd.DataFrame], Dict[str, datetime]]:
        """Processes a single source configuration using CSV-driven mapping.

        Returns:
            Tuple of (normalized DataFrame, dict of filename -> file date)
        """
        source_name = source_config['name']
        csv_mapping_column = source_config.get('csv_mapping_column')
        file_dates = {}

        if not csv_mapping_column:
            print(f"Skipping {source_name}: no csv_mapping_column specified")
            return None, file_dates

        if csv_mapping_column not in self.field_mapping.columns:
            print(f"Skipping {source_name}: column '{csv_mapping_column}' not found in mapping CSV")
            return None, file_dates

        print(f"\nProcessing source: {source_name}")
        print(f"  Using mapping column: {csv_mapping_column}")

        # Find matching files
        file_pattern = os.path.join(self.input_dir, source_config['file_pattern'])
        files = glob.glob(file_pattern)

        if not files:
            print(f"  No files found for pattern: {file_pattern}")
            return None, file_dates

        all_data = []
        for file_path in files:
            filename = os.path.basename(file_path)
            print(f"  Reading file: {filename}")

            # Extract file date for freshness tracking
            file_date = self._extract_file_date(filename)
            if file_date:
                file_dates[filename] = file_date

            try:
                # Handle both CSV and Excel files
                if file_path.lower().endswith('.xlsx') or file_path.lower().endswith('.xls'):
                    df_raw = pd.read_excel(file_path)
                else:
                    # Read only the source columns actually required by the mapping.
                    # This significantly reduces peak memory for large CSV files.
                    mapping_specs = self.field_mapping[csv_mapping_column].dropna()

                    required_source_columns = []
                    for spec in mapping_specs:
                        spec = str(spec).strip()

                        if not spec:
                            continue

                        if spec.upper() == 'NULL':
                            continue

                        if re.match(r"Hardcode\s+'[^']*'", spec, re.IGNORECASE):
                            continue

                        if spec.lower().startswith('derive from'):
                            continue

                        required_source_columns.append(spec)

                    # Read header only to identify which mapped columns actually exist.
                    csv_header = pd.read_csv(
                        file_path,
                        encoding='utf-8-sig',
                        nrows=0
                    )

                    available_columns = set(csv_header.columns)

                    usecols = [
                        column
                        for column in required_source_columns
                        if column in available_columns
                    ]

                    df_raw = pd.read_csv(
                        file_path,
                        encoding='utf-8-sig',
                        usecols=usecols
                    )

                print(f"    Raw rows: {len(df_raw):,}, columns: {len(df_raw.columns)}")

                # Apply CSV-driven field mapping
                df_normalized = self._apply_csv_mapping(
                    df_raw,
                    csv_mapping_column,
                    source_config
                )

                # Release the raw source DataFrame before retaining the normalized data.
                del df_raw

                all_data.append(df_normalized)
                print(f"    Normalized rows: {len(df_normalized):,}")

                del df_normalized

            except Exception as e:
                print(f"  Error processing file {file_path}: {e}")
                import traceback
                traceback.print_exc()

        if all_data:
            return pd.concat(all_data, ignore_index=True), file_dates
        return None, file_dates

    def _apply_csv_mapping(self, df_raw: pd.DataFrame, mapping_column: str,
                           source_config: Dict[str, Any]) -> pd.DataFrame:
        """
        Applies field mapping from CSV to raw DataFrame.

        Handles:
        - NULL → Set to None
        - Hardcode 'VALUE' → Set literal value
        - Derive from X → Set to None (handled in pre_cleaner)
        - Direct column name → Map source column to target
        """
        # Create empty DataFrame with target fields
        df_result = pd.DataFrame(index=df_raw.index)

        for _, row in self.field_mapping.iterrows():
            # print(f"row: {row.to_dict()}")
            target_field = row['Field Name']
            source_spec = row[mapping_column]
            # print(f"row['{mapping_column}']: {source_spec}")
            # Handle NULL or empty
            if pd.isna(source_spec) or str(source_spec).strip().upper() == 'NULL':
                df_result[target_field] = None
                continue

            source_spec = str(source_spec).strip()

            # Handle Hardcode 'VALUE'
            hardcode_match = re.match(r"Hardcode\s+'([^']*)'", source_spec, re.IGNORECASE)
            if hardcode_match:
                value = hardcode_match.group(1)
                df_result[target_field] = value
                continue

            # Handle Derive from X (leave for pre_cleaner to handle)
            if source_spec.lower().startswith('derive from'):
                df_result[target_field] = None  # Will be derived in enrichment step
                continue

            # Direct column mapping
            if source_spec in df_raw.columns:
                df_result[target_field] = df_raw[source_spec]
            else:
                # Column not found in source - set to None
                df_result[target_field] = None

        # Apply date formatting
        for field, dtype in self.schema_types.items():
            if dtype == 'date' and field in df_result.columns:
                df_result[field] = pd.to_datetime(df_result[field], errors='coerce')
                df_result[field] = df_result[field].dt.strftime('%Y-%m-%d')

        # Fix Excel-corrupted scientific notation IDs (e.g., '1.75223E+11' -> '175223000000')
        if 'item_id' in df_result.columns:
            sci_pattern = re.compile(r'^\d+\.\d+[eE]\+\d+$')
            sci_mask = df_result['item_id'].astype(str).str.match(sci_pattern, na=False)
            fix_count = sci_mask.sum()
            if fix_count > 0:
                df_result.loc[sci_mask, 'item_id'] = (
                    df_result.loc[sci_mask, 'item_id']
                    .astype(str)
                    .apply(lambda x: str(int(float(x))))
                )
                print(f"    Fixed {fix_count:,} scientific notation item_id values")

        # Standardize blank vendor names early for downstream joins/reporting.
        if 'vendor_name' in df_result.columns:
            df_result['vendor_name'] = (
                df_result['vendor_name']
                .astype(str)
                .str.strip()
                .replace({'': 'N/A', 'nan': 'N/A', 'None': 'N/A'})
            )

        return df_result


if __name__ == "__main__":
    # Test run
    norm = Normalizer(
        config_path="step_01_ingestion/b.config/source_mappings.yaml",
        schema_dir="step_01_ingestion/c.schemas",
        input_dir="step_01_ingestion/a.raw_data",
        output_dir="step_01_ingestion/e.normalized"
    )
    norm.process_all()
