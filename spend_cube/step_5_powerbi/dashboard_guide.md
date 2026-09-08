# Forgent Power BI Dashboard Guide

## Quick Start

1. **Open Power BI Desktop** (April 2025 or later for PBIP support)
2. **File > Open** and select `Forgent Procurement Dashboard.pbip`
   - This is a Power BI Project (PBIP) file — the semantic model, theme, measures, and all pages are bundled
   - No manual CSV import, Power Query, or DAX pasting required
3. **Refresh data** if the underlying `po_fact_table.csv` has been updated

### Project Structure

```
Forgent Procurement Dashboard.pbip          ← Open this file
Forgent Procurement Dashboard.Report/      ← Report pages, visuals, theme
Forgent Procurement Dashboard.SemanticModel/ ← Data model, measures, relationships
```

---

## Global Controls

Every page (except Cover and Notes) shares this layout:

```
┌────────────────────────────────────────────────────────────────┐
│  Page Title                                                     │
├───────────┬──[Date Perspective]──[Business Unit]──[Txn Type]───┤
│  Filters  │  [Card] [Card] [Card] [Card] [Card]               │
│           ├────────────────────────────────────────────────────-│
│  Date     │                                                     │
│  Cat L1   │                  Main Content Area                  │
│  Cat L2   │           (charts, tables, pivot tables)            │
│  Cat L3   │                                                     │
│  Supplier │                                                     │
│  Item     ├─────────────────────────────────────────────────────┤
│  PO #     │                                                     │
│  Buyer    │             Secondary Content Area                  │
│           │                                                     │
└───────────┴─────────────────────────────────────────────────────┘
```

**Top-row advanced slicers:**
- **Date Perspective** — switches between Receipt Date and Order Date analysis
- **Business Unit** — filters to States (EPICOR) or PwrQ (NetSuite)
- **Transaction Type** — filters to Receipts, Open Orders, etc.

**Left sidebar dropdown slicers:** Date (hierarchy), Category L1/L2/L3, Supplier, Item, PO Number, Buyer

**Report-level filter:** `intercompany = 'N'` (excludes intercompany transactions globally)

---

## Dashboard Pages (15)

### 1. Cover

Title page with Forgent logo and "Spend Visibility Dashboard" heading.

---

### 2. Executive Spend Summary

High-level KPI overview across all spending.

**Cards:** Total Spend | YoY % | Supplier Count | Item Count | Avg Order Value

```
┌─────────────────────────────────────────────────────────────┐
│              Spend vs Prior Year (Area Chart)               │
│         X: Month   Y: Total Spend + Prior Year Spend        │
├──────────────────────────┬──────────────────────────────────┤
│  Spend by Business Unit  │  Spend by Supplier              │
│  (Donut Chart)           │  (Clustered Bar Chart)           │
│  States vs PwrQ          │  Top suppliers by Total Spend    │
└──────────────────────────┴──────────────────────────────────┘
```

---

### 3. Category Overview

Category-level spend analysis with trend and breakdown.

**Cards:** 5 KPI cards including YoY Growth Leader (Category)

```
┌─────────────────────────────────────────────────────────────┐
│              Category Spend Trend (Area Chart)              │
│              X: Month   Y: Total Spend                      │
├──────────────────────────┬──────────────────────────────────┤
│  Category Breakdown      │  Category Detail (Pivot Table)   │
│  (Bar Chart)             │  Rows: L1 > L2 > L3 > Item      │
│  By item_category_l1     │  Cols: Business Unit             │
│                          │  Vals: Spend, Qty, Open, Recv'd  │
└──────────────────────────┴──────────────────────────────────┘
```

---

### 4. Supplier Overview

Supplier concentration and top-supplier metrics.

**Cards:** 5 supplier KPI cards

```
┌─────────────────────────────────────────────────────────────┐
│              Supplier Spend Trend (Area Chart)              │
│              X: Month   Y: Supplier spend                   │
├──────────────────────────┬──────────────────────────────────┤
│  Supplier Breakdown      │  Supplier Detail (Pivot Table)   │
│  (Bar Chart)             │  Rows: Supplier > Category       │
│  Top suppliers by spend  │  Vals: Spend, performance metrics│
└──────────────────────────┴──────────────────────────────────┘
```

---

### 5. Supplier Risk & Opportunity

Risk metrics, concentration analysis, and overdue tracking.

**Cards:** Top 3 Concentration % | Top 10 Concentration % | Overdue Amount | Overdue PO Lines | Weighted Lead Time

```
┌────────────────────────────┬────────────────────────────────┐
│  Pareto 80/20 Analysis     │  Top Supplier Share of Category│
│  (Combo Chart)             │  (Clustered Bar Chart)         │
│  X: Supplier Rank          │  By item_category_l1/l2/l3     │
│  Y1: Spend at Rank         │  Y: Top Supplier Share %       │
│  Y2: Cumulative %          │  Labels: Top Supplier Name     │
├────────────────────────────┼────────────────────────────────┤
│  Spend by Supplier Type    │  Overdue Details (Pivot Table) │
│  (Column Chart)            │  Rows: Supplier > PO > Item    │
│  X: supplier_type          │  Vals: Overdue Amt, Count,     │
│  Y: Total Spend            │    Lead Time, Open/Recv'd Spend│
└────────────────────────────┴────────────────────────────────┘
```

---

### 6. Operational Performance

On-time delivery, lead times, and date coverage.

**Cards:** OTD % (Due) | OTD % (Promise) | Avg Days Late (Due) | Avg Days Late (Promise) | additional metrics

```
┌─────────────────────────────────────────────────────────────┐
│        OTD % Trend (Line Chart)                             │
│        X: Month   Y: OTD % (Due Date) + Avg Days Late      │
├──────────────────────────┬──────────────────────────────────┤
│  Date Coverage           │  Supplier Performance            │
│  (Pivot Table)           │  (Pivot Table)                   │
│  Rows: Coverage measures │  Rows: Supplier > Category > Item│
│  Cols: Business Unit     │  Vals: Spend, Avg Lead Time,     │
│  Vals: Selected Coverage │    OTD %, Days Late, Coverage %  │
└──────────────────────────┴──────────────────────────────────┘
```

---

### 7. Buyer Performance

Buyer-level spend analysis, workload distribution, and performance metrics.

**Cards:** Total Spend | Buyer Count | Avg Spend per Buyer | OTD % (Due) | Supplier Count

```
┌─────────────────────────────────────────────────────────────┐
│              Buyer Spend Trend (Area Chart)                  │
│              X: Month   Y: Total Spend + Prior Year Spend    │
├──────────────────────────┬──────────────────────────────────┤
│  Spend by Buyer           │  Buyer Detail (Pivot Table)      │
│  (Clustered Bar Chart)    │  Rows: Buyer > Supplier > Cat L1 │
│  By buyer_id              │  Vals: Spend, Order Count,        │
│  Y: Total Spend           │    Supplier Count, OTD %, Lead T  │
└──────────────────────────┴──────────────────────────────────┘
```

**Purpose:** Evaluate buyer workload, identify spend concentration by buyer, and compare delivery performance across the procurement team.

---

### 8. Raw Material vs Index

Copper price index overlay with paid pricing comparison.

**Cards:** 3 raw-material KPI cards

```
┌─────────────────────────────────────────────────────────────┐
│     Copper Market vs Paid Price (Line Chart)                │
│     X: Month   Y: Market price + Paid price per lb          │
├──────────────────────────┬──────────────────────────────────┤
│  Material Comparison     │  Material Cost Detail            │
│  (Pivot Table)           │  (Table)                         │
│  Category/item breakdown │  Line-level material costs       │
└──────────────────────────┴──────────────────────────────────┘
```

**Purpose:** Identify premium/discount vs market, timing correlation, strategic purchasing opportunities, and vendor negotiation leverage.

---

### 9. Price & Cost Analysis

Unit cost trends and price variance tracking.

**Cards:** 3 pricing KPI cards

```
┌─────────────────────────────────────────────────────────────┐
│     Price/Cost Trend (Line Chart)                           │
│     X: Month   Y: Cost metrics                              │
├──────────────────────────┬──────────────────────────────────┤
│  Item Pricing Summary    │  Item Pricing Detail             │
│  (Pivot Table)           │  (Table)                         │
│  Rows: Item short name,  │  Line-level pricing data         │
│    ID, description       │                                  │
│  Vals: Cost measures     │                                  │
└──────────────────────────┴──────────────────────────────────┘
```

---

### 10. PO Explorer

Searchable, sortable purchase order detail table.

```
┌─────────────────────────────────────────────────────────────┐
│  [Advanced Slicers for quick filtering]                     │
├─────────────────────────────────────────────────────────────┤
│  PO Detail Table                                            │
│  Columns: Company, Type, PO #, Line #, Supplier,           │
│           Item, Dates, Quantities, Amounts, Status          │
│  (full-width scrollable table)                              │
└─────────────────────────────────────────────────────────────┘
```

---

### 11. Part Explorer

Searchable item-level detail table.

```
┌─────────────────────────────────────────────────────────────┐
│  [Advanced Slicers for quick filtering]                     │
├─────────────────────────────────────────────────────────────┤
│  Parts Detail Table                                         │
│  Columns: Item ID, Item Name, Total Spend, Total Qty,       │
│           Avg Unit Cost, Total Weight (Lbs), ...            │
│  (full-width scrollable table)                              │
└─────────────────────────────────────────────────────────────┘
```

---

### 12. Transaction Explorer

Four pivot matrices for multi-dimensional drill-down.

```
┌────────────────────────────┬────────────────────────────────┐
│  Category Explorer         │  PO Explorer                   │
│  (Pivot Table)             │  (Pivot Table)                 │
│  L1 > L2 > L3 > Item      │  PO-based hierarchy            │
├────────────────────────────┼────────────────────────────────┤
│  Supplier Explorer         │  Business Unit Explorer        │
│  (Pivot Table)             │  (Pivot Table)                 │
│  Supplier > Category       │  BU columns with dimensions    │
└────────────────────────────┴────────────────────────────────┘
```

---

### 13. Open Order Pipeline

Forward-looking view of all open purchase orders in the pipeline.

**Page-level filter:** `is_open_order = true`

**Cards:** Pipeline Amount | Open POs | Open Lines | Overdue Amount | Due Next 30 Days

```
┌─────────────────────────────────────────────────────────────┐
│  Open Amount by Supplier (Clustered Bar Chart)              │
│  Y: Supplier   X: Open Lines – Remaining Amount             │
├─────────────────────────────────────────────────────────────┤
│  Open Order Detail (Table)                                  │
│  Columns: Company, PO #, Line #, Supplier, Buyer, Item,    │
│           Dates, Days Until Due, Amounts, Status, Categories│
│  (full-width scrollable table)                              │
└─────────────────────────────────────────────────────────────┘
```

**Purpose:** Monitor the open order pipeline, identify upcoming due dates, track supplier exposure, and spot at-risk deliveries before they become overdue.

---

### 14. Overdue POs

Filtered view showing only overdue orders.

**Page-level filter:** `is_overdue = true`

**Cards:** 5 overdue-specific KPI cards

```
┌─────────────────────────────────────────────────────────────┐
│  [Advanced Slicers for quick filtering]                     │
├─────────────────────────────────────────────────────────────┤
│  Overdue POs Detail Table                                   │
│  Columns: Company, PO #, Line #, Release #, Supplier,      │
│           Item, Dates, Status                               │
│  (full-width scrollable table)                              │
└─────────────────────────────────────────────────────────────┘
```

---

### 15. Notes

Free-text notes page (single textbox).

---

## Semantic Model

### Tables

| Table | Type | Description |
|-------|------|-------------|
| po_fact_table | Fact | 73+ columns — PO/receipt transactions with quantities, amounts, dates, categories, specs |
| DimSupplier | Dimension | Derived: standardized_vendor_name, supplier_type, vendor_location, intercompany |
| DimCategory | Dimension | Derived: item_category_l1 |
| DimItem | Dimension | Derived: item_id, item_name, item_name_mpn, item_short_name, item_display_name, item_category_l1 |
| Time Intelligence | Calendar | Generated dates 2021–2027 with Year, Quarter, Month, Day of Week, Is Weekday |
| DatePerspective | Parameter | Toggles between "Receipt Date" and "Order Date" for time intelligence |
| SupplierRankAxis | Parameter | Generates rank series 1–5000 for Pareto/concentration analysis |
| DateCoverageMeasureList | Parameter | Lookup table for 8 date-coverage metrics (enables measure switching in visuals) |
| CopperPriceIndex | Derived | Copper commodity price per lb by year-month |

### Key Relationships

- `po_fact_table.analysis_date → Time Intelligence.Date` (active — default time axis)
- `po_fact_table.order_date → Time Intelligence.Date` (inactive — activated via USERELATIONSHIP)
- `po_fact_table → DimSupplier` on standardized_vendor_name
- `po_fact_table → DimCategory` on item_category_l1
- `po_fact_table → DimItem` on item_id
- Multiple date columns → auto-generated LocalDateTables (due_date, promise_date, receipt_date, expected_receipt_date, arrived_date)

---

## Measures (85+)

Organized into display folders in the Measure Table:

| Folder | Key Measures |
|--------|-------------|
| **01 - KPIs** | Total Spend, Avg Order Value, Avg Unit Cost, Order Count, Line Count, Supplier Count, Item Count, Total Quantity, Data As Of |
| **02 - Time Intelligence** | YTD/QTD/MTD Spend, Prior Year Spend, YoY %, Rolling 12M Spend, YoY Unit Cost %, PPV Savings |
| **03 - Business Unit** | States Spend (EPICOR), PwrQ Spend (NetSuite) |
| **04 - Supplier Analysis** | Top 10/Top 3 Supplier Concentration %, Spend at Rank, Cum %, Supplier Count @ 80%, Supplier Share of Category, Top Supplier Name/Share %, New Vendors (YTD) |
| **05 - Category Analysis** | Top Category Name/Spend/Supplier Count, Category YoY %, YoY Growth Leader, Avg Vendors per Category, Multi-Source Items, Items with Price Increase |
| **06 - Operations** | Open Orders/Lines, Overdue Amount/Count, Avg Lead Time, OTD % (Due/Promise), Late/Early Count, Avg Days Late, Weighted Lead Time, OTD Eligible Lines |
| **07 - Date Coverage** | Coverage % for Due/Promise/Receipt/Expected/Arrived dates, Date Completeness Score, Missing Dates Count |
| **08 - Receipts & Backlog** | Received Spend/Quantity, Open Spend/Qty |
| **09 - Raw Materials** | Avg Cost Per Lb, Total Weight, Weighted Avg Cost Per Lb, Copper Market Price, Copper Spend, Avg Paid Price per Lb (Copper), Copper Premium/Discount % |
| **10 - Buyer Analysis** | Buyer Count, Avg Spend per Buyer |
| **11 - Open Order Pipeline** | Open Line Count, Due Next 7 Days, Due Next 30 Days |
| **_Base** | Hidden base measures for calculated fields |

---

## Theme & Colors

Dual theme system: Microsoft `CY25SU11` base + custom `Forgent_Power_Solutions` overlay.

| Element | Hex | Usage |
|---------|-----|-------|
| Primary | #008B8B | Headers, accents, States data |
| Accent | #73F3FF | Highlights, PwrQ data |
| Background | #FAFAFA | Page background |
| Text | #000405 | All text |
| Secondary | #2F4F4F | Secondary elements |
| Light | #AFEEEE | Light accents, grid lines |

**Conditional formatting indicators:** Green (#1AAB40) Good, Yellow (#D9B300) Neutral, Red (#D64554) Bad.

---

## Tips

1. **Date Perspective** — use the top-row slicer to switch between Order Date and Receipt Date views; measures auto-adjust via USERELATIONSHIP
2. **Intercompany** — excluded at the report level; to include, edit the report-level filter
3. **Supplier Rank (Pareto)** — the SupplierRankAxis parameter table drives the 80/20 analysis on the Risk page
4. **Date Coverage** — the Operational Performance page shows completeness % for each date field; use this to assess data quality
5. **Copper overlay** — Raw Material vs Index page compares your paid copper price against Comex market pricing
