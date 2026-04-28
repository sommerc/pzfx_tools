# GraphPad Prism pzfx Tools

Tools for filling GraphPad Prism `.pzfx` template files with tab-separated data.

This is specialized code for the [Sweeney lab](https://ista.ac.at/en/research/sweeney-group/), ISTA

## Installation

```bash
git clone https://github.com/sommerc/pzfx_tools.git
pip install -e pzfx_tools/
```

Or **run directly** without installing via [uvx](https://docs.astral.sh/uv/):

```bash
uvx --from https://github.com/sommerc/pzfx_tools.git <COMMAND> ...
```

---

## Commands

### `pzfx-fill`

Fills **OneWay** tables in a `.pzfx` template with data from a `.tab` file.
Each selected feature column becomes a set of Y-columns, grouped by Stage or Genotype.

**Usage**

```
pzfx-fill TEMPLATE.pzfx DATA_TABLE.tab OUTPUT.pzfx
```

**Interactive prompts**

| Step | Description |
|------|-------------|
| Group by | Choose whether tables are grouped by **Stage** or **Genotype** |
| Subgroup | Select a single value for the other dimension (e.g. one Genotype if grouping by Stage) |
| feature_for | *(optional)* Filter rows by `feature_for` category — produces one table per selected value |
| Features | Choose which data columns become Y-columns |

**Expected metadata columns in the data file**

```
Movie  Stage  Genotype  Frames  Track_idx  Name  feature_for
```

All other columns are treated as feature data and offered for selection.

---

### `pzfx-fill-frequency`

Fills **XY replicate** tables in a `.pzfx` template with frequency spectrum data.
Each `feature_for` value becomes a separate table. The X axis holds the frequency bins;
individual tracks are stored as replicate subcolumns within each group column.

**Usage**

```
pzfx-fill-frequency TEMPLATE.pzfx DATA_TABLE.tab OUTPUT.pzfx
```

**Interactive prompts**

| Step | Description |
|------|-------------|
| Group by | Choose whether columns are grouped by **Stage** or **Genotype** |
| Subgroup | Select a single value for the other dimension |
| feature_for | Select which `feature_for` values to include — one table is created per value |

**Expected data format**

- Metadata columns: `Movie`, `Stage`, `Genotype`, `Track_idx`, `feature_for`
- Frequency bin columns: any column whose name parses as a float (e.g. `30.0`, `25.8`, …, `0.9375`)
- All 24 frequency bins are used automatically — no manual feature selection needed

**Output table structure**

```
X axis   → frequency bins (0.9375 – 30.0 Hz)
Columns  → one per Stage or Genotype
Rows     → one replicate subcolumn per track
Title    → feature_for value (e.g. "tail_2")
```
