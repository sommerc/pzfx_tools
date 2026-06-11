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

Fills **OneWay** tables in a `.pzfx` template with data from one or more `.tab` files.
Each selected feature column becomes a set of Y-columns, grouped by Stage or Genotype.

**Usage**

```
pzfx-fill TEMPLATE.pzfx DATA.tab OUTPUT.pzfx
pzfx-fill TEMPLATE.pzfx DATA1.tab DATA2.tab ... OUTPUT.pzfx
```

When multiple data files are provided, rows are concatenated. The last positional argument
is always the output path; all preceding arguments after the template are data files.

**Interactive prompts**

| Step | Scope | Description |
|------|-------|-------------|
| Group by | global | Choose whether tables are grouped by **Stage** or **Genotype** |
| Subgroup | global | Select a single value for the other dimension (e.g. one Genotype if grouping by Stage) |
| feature_for | per file | *(optional)* Filter rows by `feature_for` category — one table per selected value |
| Features | per file | Choose which data columns become Y-columns |

When multiple data files are given, the grouping and subgroup selection happen once
(from the combined pool of all files). The `feature_for` and feature selections are then
made independently for each file, since different files may contain different feature columns.

**Left/right body-joint handling**

If the `feature_for` column contains bilateral pairs (e.g. `left_ankle` / `right_ankle`,
or background-subtracted variants `bs_left_ankle` / `bs_right_ankle`), the selection list
collapses each pair to its base name:

- `ankle` — plain left/right pair
- `ankle [bs]` — background-subtracted pair

Joints are sorted anatomically: background-subtracted pairs first (arm joints, then leg
joints), followed by plain pairs in the same order.

When one or more pairs are selected, a single global prompt asks how to handle all of them:

| Option | Result |
|--------|--------|
| **Separate columns** | One Y-column per group × side (`WT left`, `WT right`, …) within one table |
| **Negate one side and combine** | Right-side values are negated before pooling with the left side, aligning mirror-convention angle measurements |

**Input validation**

Before any prompts, each data file is checked for:

- Required metadata columns `Stage` and `Genotype`
- At least one feature column (non-metadata, non-float-named)
- *(multi-file)* Whether `feature_for` is present in some files but absent in others (warning only)

**Expected metadata columns in the data file**

```
Movie  Stage  Genotype  Frames  Track_idx  Name  feature_for
```

Columns whose names parse as a float (frequency bin headers) are automatically excluded
from the feature selection.

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

Left/right pair collapsing and the combine/separate prompt work the same way as in
`pzfx-fill` (see above). For frequency/power data no value transformation is applied
when combining — tracks from both sides are pooled directly.

**Input validation**

Before any prompts, the data file is checked for:

- Required metadata columns `Stage` and `Genotype`
- At least one float-named frequency bin column

**Expected data format**

- Metadata columns: `Movie`, `Stage`, `Genotype`, `Track_idx`, `feature_for`
- Frequency bin columns: any column whose name parses as a float (e.g. `30.0`, `25.8`, …, `0.9375`)
- All detected frequency bins are used automatically — no manual feature selection needed

**Output table structure**

```
X axis   → frequency bins (0.9375 – 30.0 Hz)
Columns  → one per Stage or Genotype
Rows     → one replicate subcolumn per track
Title    → feature_for value (e.g. "tail_2")
```
