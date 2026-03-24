# GraphPad Prism pzfx Tools

Collections of tools to help with Prism analysis

## Command Line Tools

### pzfx-fill
Replaces the data tables in `TEMOLATE.pzfx` with data from a .tab separated `DATA_TABLE.tab`

Expected meta-data columns in `DATA_TABLE.tab` are:

```python
{"Movie", "Stage", "Genotype", "Frames", "Track_idx", "feature_for",}
```

Usage:

```
uvx --from https://github.com/sommerc/pzfx_tools.git pzfx-fill TEMPLATE.pzfx DATA_TABLE.tab OUTPUT.pzfx
```
