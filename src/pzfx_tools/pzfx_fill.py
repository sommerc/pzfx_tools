#!/usr/bin/env python3
"""Interactive GraphPad Prism .pzfx generator.

Prompts the user to choose:
  - Group tables by Stage or Genotype
  - Which features become YColumns
  - Which stages / genotypes to include

Usage:
  python pzfx_fill.py template.pzfx data.tab output.pzfx
"""

import argparse
import csv
import sys
import xml.etree.ElementTree as ET

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

console = Console()

# ── data helpers ──────────────────────────────────────────────────────────────

META_COLS = {"Movie", "Stage", "Genotype", "Frames", "Track_idx", "Name", "feature_for", ""}


def read_tab(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def get_meta(rows: list[dict]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (features, stages, genotypes, feature_for_values)."""
    if not rows:
        return [], [], [], []
    features = [c for c in rows[0] if c not in META_COLS]
    stages = sorted({r.get("Stage", "").strip() for r in rows} - {""})
    genotypes = sorted({r.get("Genotype", "").strip() for r in rows} - {""})
    feature_for_values = sorted({r.get("feature_for", "").strip() for r in rows} - {""})
    return features, stages, genotypes, feature_for_values


# ── interactive prompts ───────────────────────────────────────────────────────


def _print_numbered(title: str, items: list[str]) -> None:
    t = Table(title=title, show_header=False, box=None, padding=(0, 1))
    t.add_column("num", style="bold cyan", no_wrap=True)
    t.add_column("item", style="bright_white")
    for i, item in enumerate(items, 1):
        t.add_row(f"[{i}]", item)
    console.print(t)


def _parse_selection(
    raw: str, items: list[str], single: bool = False
) -> list[str] | None:
    """Parse a comma/space-separated list of numbers or 'all'. Returns None on error."""
    raw = raw.strip()
    if not single and raw.lower() == "all":
        return list(items)
    selected = []
    for token in raw.replace(",", " ").split():
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                return None
            start, end = int(parts[0]) - 1, int(parts[1]) - 1
            if not (0 <= start <= end < len(items)):
                return None
            selected.extend(items[start : end + 1])
        elif token.isdigit():
            idx = int(token) - 1
            if not (0 <= idx < len(items)):
                return None
            selected.append(items[idx])
        else:
            return None
    if single and len(selected) > 1:
        return None
    return selected


def ask_selection(
    title: str, items: list[str], required: bool = True, single: bool = False
) -> list[str]:
    """Show numbered list and ask user to pick items. Returns selected list."""
    console.print()
    _print_numbered(title, items)
    if single:
        console.print("[dim]Enter exactly one number[/dim]")
    else:
        console.print(
            "[dim]Enter numbers, ranges, or [bold]all[/bold]  [italic](e.g. 1-4,6)[/italic][/dim]"
        )
    while True:
        raw = Prompt.ask(
            "[bold green]Selection[/bold green]", default="" if single else "all"
        )
        result = _parse_selection(raw, items, single=single)
        if result is None:
            if single:
                console.print("[red]Invalid input — enter exactly one number[/red]")
            else:
                console.print(
                    "[red]Invalid input — use numbers, ranges, or all  (e.g. 1-4,6)[/red]"
                )
            continue
        if required and not result:
            console.print("[red]Please select at least one item.[/red]")
            continue
        return result


def ask_group_by() -> str:
    console.print()
    console.print("[bold cyan]Group tables by:[/bold cyan]")
    console.print("  [bold cyan][1][/bold cyan] Stage")
    console.print("  [bold cyan][2][/bold cyan] Genotype")
    while True:
        raw = Prompt.ask("[bold green]Selection[/bold green]", default="1")
        if raw.strip() == "1":
            return "stage"
        if raw.strip() == "2":
            return "genotype"
        console.print("[red]Enter 1 or 2.[/red]")


def _detect_lr_pairs(ff_values: list[str]) -> dict[str, tuple[str, str]]:
    """Return {base: (left_XXX, right_XXX)} for every left_/right_ pair present."""
    left_map = {v[5:]: v for v in ff_values if v.startswith("left_")}
    right_map = {v[6:]: v for v in ff_values if v.startswith("right_")}
    return {base: (left_map[base], right_map[base]) for base in left_map if base in right_map}


def ask_feature_fors_with_lr(
    available_ff: list[str],
) -> list[str | tuple[str, list[str]]]:
    """Prompt for feature_for selection, collapsing left_/right_ pairs into base names."""
    pairs = _detect_lr_pairs(available_ff)
    paired_raw = {v for lf, rf in pairs.values() for v in (lf, rf)}

    seen_bases: set[str] = set()
    display_items: list[str] = []
    for ff in available_ff:
        if ff in paired_raw:
            base = ff[5:] if ff.startswith("left_") else ff[6:]
            if base not in seen_bases:
                seen_bases.add(base)
                display_items.append(base)
        else:
            display_items.append(ff)

    selected = ask_selection("Select feature_for", display_items, single=False)

    result: list[str | tuple[str, list[str]]] = []
    for item in selected:
        if item in pairs:
            left_ff, right_ff = pairs[item]
            console.print(f"\n[bold cyan]'{item}'[/bold cyan] has left/right variants:")
            console.print(f"  [bold cyan][1][/bold cyan] Separate columns  (left_{item} / right_{item})")
            console.print("  [bold cyan][2][/bold cyan] Combine left and right into one column  [dim](absolute values)[/dim]")
            while True:
                raw = Prompt.ask("[bold green]Selection[/bold green]", default="2")
                if raw.strip() == "1":
                    result.append(left_ff)
                    result.append(right_ff)
                    break
                if raw.strip() == "2":
                    result.append((item, [left_ff, right_ff]))
                    break
                console.print("[red]Enter 1 or 2.[/red]")
        else:
            result.append(item)
    return result


# ── pzfx builder ──────────────────────────────────────────────────────────────


def build_pzfx(
    template_path: str,
    rows: list[dict],
    group_by: str,  # "stage" or "genotype"
    selected_features: list[str],
    selected_stages: list[str],
    selected_genotypes: list[str],
    selected_feature_fors: list[str | tuple[str, list[str]]],
    output_path: str,
) -> int:
    """Build the .pzfx file and return the number of tables written."""
    ET.register_namespace("dt", "urn:schemas-microsoft-com:datatypes")
    tree = ET.parse(template_path)
    root = tree.getroot()

    # ── remove all existing Tables ──
    table_seq = root.find("TableSequence")
    if table_seq is not None:
        for ref in list(table_seq):
            table_seq.remove(ref)
    for table in root.findall("Table"):  # direct children only
        root.remove(table)

    # ── determine groups / subgroups ──
    if group_by == "stage":
        groups = selected_stages
        subgroups = selected_genotypes
        group_col = "Stage"
        subgroup_col = "Genotype"
    else:
        groups = selected_genotypes
        subgroups = selected_stages
        group_col = "Genotype"
        subgroup_col = "Stage"

    subgroup = subgroups[0] if len(subgroups) == 1 else ""

    # ── create new Tables (one per feature × feature_for) ──
    ff_list = selected_feature_fors if selected_feature_fors else [None]
    table_idx = 0
    for feature in selected_features:
        for ff_entry in ff_list:
            if ff_entry is None:
                ff_display: str | None = None
                ff_filter: list[str] | None = None
            elif isinstance(ff_entry, tuple):
                ff_display, ff_filter = ff_entry[0], list(ff_entry[1])
            else:
                ff_display = ff_entry
                ff_filter = [ff_entry]

            table_id = f"Table{1000 + table_idx}"
            table_idx += 1

            if table_seq is not None:
                ref_el = ET.SubElement(table_seq, "Ref")
                ref_el.set("ID", table_id)

            table_el = ET.SubElement(root, "Table")
            table_el.set("ID", table_id)
            table_el.set("XFormat", "none")
            table_el.set("TableType", "OneWay")
            table_el.set("EVFormat", "AsteriskAfterNumber")

            title_el = ET.SubElement(table_el, "Title")
            base_title = f"{feature} ({ff_display})" if ff_display else feature
            title_el.text = f"{base_title} ({subgroup})" if subgroup else base_title

            # ── one YColumn per group (stage or genotype), skip if empty ──
            for group in groups:
                sub_rows = [
                    r
                    for r in rows
                    if r.get(group_col, "").strip() == group
                    and (not subgroup or r.get(subgroup_col, "").strip() == subgroup)
                    and (ff_filter is None or r.get("feature_for", "").strip() in ff_filter)
                ]
                values = [r.get(feature, "").strip() for r in sub_rows]
                if not any(values):
                    continue

                ycol_el = ET.SubElement(table_el, "YColumn")
                ycol_el.set("Width", "81")
                ycol_el.set("Decimals", "14")
                ycol_el.set("Subcolumns", "1")

                ycol_title = ET.SubElement(ycol_el, "Title")
                ycol_title.text = group

                sub_el = ET.SubElement(ycol_el, "Subcolumn")

                for val in values:
                    d_el = ET.SubElement(sub_el, "d")
                    if val and ff_filter and len(ff_filter) > 1:
                        try:
                            val = str(abs(float(val)))
                        except ValueError:
                            pass
                    d_el.text = val if val else None

    ET.indent(root, space="\t")
    tree.write(output_path, encoding="unicode", xml_declaration=True)
    return table_idx


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill a GraphPad Prism .pzfx with TSV data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("template", help="Template .pzfx file")
    parser.add_argument("data", help="Tab-separated data file (.tab / .tsv)")
    parser.add_argument("output", help="Output .pzfx file")
    args = parser.parse_args()

    rows = read_tab(args.data)
    if not rows:
        console.print("[red]Error: data file is empty.[/red]")
        return 1

    features, stages, genotypes, feature_for_values = get_meta(rows)

    if not features:
        console.print("[red]Error: no feature columns found in data file.[/red]")
        return 1

    console.print(f"\n[bold]pzfx_fill[/bold] — [dim]{args.data}[/dim]")

    group_by = ask_group_by()

    if group_by == "stage":
        sel_genotypes = ask_selection("Select the Genotype", genotypes, single=True)
        sel_stages = ask_selection("Choose Stages", stages, single=False)
    elif group_by == "genotype":
        sel_stages = ask_selection("Select the Stage", stages, single=True)
        sel_genotypes = ask_selection("Choose Genotypes", genotypes, single=False)

    sel_feature_for: list[str] = []
    if feature_for_values:
        # Only offer feature_for values that actually co-occur with the chosen
        # subgroup AND at least one of the selected groups, so the user cannot
        # pick a combination that yields zero data rows and empty tables.
        if group_by == "stage":
            subgroup_col, subgroup_val = "Genotype", sel_genotypes[0]
            group_col_ff, group_vals_ff = "Stage", set(sel_stages)
        else:
            subgroup_col, subgroup_val = "Stage", sel_stages[0]
            group_col_ff, group_vals_ff = "Genotype", set(sel_genotypes)
        available_ff = sorted(
            {r.get("feature_for", "").strip() for r in rows
             if r.get(subgroup_col, "").strip() == subgroup_val
             and r.get(group_col_ff, "").strip() in group_vals_ff}
            - {""}
        )
        if available_ff:
            sel_feature_for = ask_feature_fors_with_lr(available_ff)
        else:
            console.print("[yellow]No feature_for values found for the selected stage/genotype combination.[/yellow]")

    sel_features = ask_selection("Features (YColumns)", features, single=False)

    n = build_pzfx(
        template_path=args.template,
        rows=rows,
        group_by=group_by,
        selected_features=sel_features,
        selected_stages=sel_stages,
        selected_genotypes=sel_genotypes,
        selected_feature_fors=sel_feature_for,
        output_path=args.output,
    )

    console.print(
        f"\n[bold green]Done.[/bold green] Written [cyan]{n}[/cyan] table(s) "
        f"(grouped by [cyan]{group_by}[/cyan], "
        f"[cyan]{len(sel_features)}[/cyan] feature(s)) "
        f"→ [bold]{args.output}[/bold]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
