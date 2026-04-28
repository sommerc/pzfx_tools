#!/usr/bin/env python3
"""Interactive GraphPad Prism .pzfx generator for frequency spectrum data.

Fills XY-replicate tables where:
  - X axis  = frequency bins (detected from float-named columns)
  - Rows    = individual tracks (one <Subcolumn> per track)
  - Columns = groups (Stage or Genotype)
  - Tables  = one per feature_for pivot value

Usage:
  pzfx-fill-frequency template.pzfx data.tab output.pzfx
"""

import argparse
import csv
import sys
import xml.etree.ElementTree as ET

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

console = Console()

META_COLS = {"Movie", "Stage", "Genotype", "Frames", "Track_idx", "Name", "feature_for", ""}


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def read_tab(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def get_freq_meta(rows: list[dict]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (freq_bins, stages, genotypes, feature_for_values)."""
    if not rows:
        return [], [], [], []
    freq_bins = [c for c in rows[0] if c not in META_COLS and _is_float(c)]
    stages = sorted({r.get("Stage", "").strip() for r in rows} - {""})
    genotypes = sorted({r.get("Genotype", "").strip() for r in rows} - {""})
    ff_values = sorted({r.get("feature_for", "").strip() for r in rows} - {""})
    return freq_bins, stages, genotypes, ff_values


# ── interactive prompts ───────────────────────────────────────────────────────


def _print_numbered(title: str, items: list[str]) -> None:
    t = Table(title=title, show_header=False, box=None, padding=(0, 1))
    t.add_column("num", style="bold cyan", no_wrap=True)
    t.add_column("item", style="bright_white")
    for i, item in enumerate(items, 1):
        t.add_row(f"[{i}]", item)
    console.print(t)


def _parse_selection(raw: str, items: list[str], single: bool = False) -> list[str] | None:
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


# ── pzfx builder ──────────────────────────────────────────────────────────────


def build_pzfx_frequency(
    template_path: str,
    rows: list[dict],
    group_by: str,
    selected_stages: list[str],
    selected_genotypes: list[str],
    selected_feature_fors: list[str],
    output_path: str,
) -> int:
    freq_bins = [c for c in rows[0] if c not in META_COLS and _is_float(c)]

    ET.register_namespace("dt", "urn:schemas-microsoft-com:datatypes")
    tree = ET.parse(template_path)
    root = tree.getroot()

    table_seq = root.find("TableSequence")
    if table_seq is not None:
        for ref in list(table_seq):
            table_seq.remove(ref)
    for tbl in root.findall("Table1024"):
        root.remove(tbl)
    for tbl in root.findall("HugeTable"):
        root.remove(tbl)

    if group_by == "stage":
        groups, group_col = selected_stages, "Stage"
        subgroups, subgroup_col = selected_genotypes, "Genotype"
    else:
        groups, group_col = selected_genotypes, "Genotype"
        subgroups, subgroup_col = selected_stages, "Stage"

    subgroup = subgroups[0] if len(subgroups) == 1 else ""

    ff_list = selected_feature_fors if selected_feature_fors else [None]
    table_idx = 0

    for ff in ff_list:
        table_id = f"Table{1000 + table_idx}"
        table_idx += 1

        if table_seq is not None:
            ET.SubElement(table_seq, "Ref").set("ID", table_id)

        max_reps = max(
            sum(
                1
                for r in rows
                if r.get(group_col, "").strip() == g
                and (not subgroup or r.get(subgroup_col, "").strip() == subgroup)
                and (ff is None or r.get("feature_for", "").strip() == ff)
            )
            for g in groups
        )

        tbl_el = ET.SubElement(root, "Table1024")
        tbl_el.set("ID", table_id)
        tbl_el.set("XFormat", "numbers")
        tbl_el.set("YFormat", "replicates")
        tbl_el.set("Replicates", str(max_reps))
        tbl_el.set("TableType", "XY")
        tbl_el.set("EVFormat", "AsteriskAfterNumber")

        title_text = ff if ff else "Frequency"
        if subgroup:
            title_text += f" ({subgroup})"
        ET.SubElement(tbl_el, "Title").text = title_text

        rtc = ET.SubElement(tbl_el, "RowTitlesColumn")
        rtc.set("Width", "1")
        ET.SubElement(rtc, "Subcolumn")

        sct = ET.SubElement(tbl_el, "SubColumnTitles")
        sct.set("OwnSet", "0")
        for _ in range(max_reps):
            ET.SubElement(sct, "Subcolumn")

        for tag, extra in [("XColumn", {}), ("XAdvancedColumn", {"Version": "1"})]:
            xcol = ET.SubElement(tbl_el, tag)
            for k, v in extra.items():
                xcol.set(k, v)
            xcol.set("Width", "78")
            xcol.set("Subcolumns", "1")
            xcol.set("Decimals", "8")
            ET.SubElement(xcol, "Title")
            x_sub = ET.SubElement(xcol, "Subcolumn")
            for bin_col in freq_bins:
                ET.SubElement(x_sub, "d").text = bin_col

        for group in groups:
            sub_rows = [
                r
                for r in rows
                if r.get(group_col, "").strip() == group
                and (not subgroup or r.get(subgroup_col, "").strip() == subgroup)
                and (ff is None or r.get("feature_for", "").strip() == ff)
            ]
            if not sub_rows:
                continue

            n = len(sub_rows)
            ycol = ET.SubElement(tbl_el, "YColumn")
            ycol.set("Width", str(n * 109))
            ycol.set("Decimals", "14")
            ycol.set("Subcolumns", str(n))
            ET.SubElement(ycol, "Title").text = group

            for row in sub_rows:
                sub_el = ET.SubElement(ycol, "Subcolumn")
                for bin_col in freq_bins:
                    val = row.get(bin_col, "").strip()
                    ET.SubElement(sub_el, "d").text = val if val else None

    ET.indent(root, space="\t")
    tree.write(output_path, encoding="unicode", xml_declaration=True)
    return table_idx


# ── entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fill a GraphPad Prism .pzfx with frequency spectrum data",
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

    freq_bins, stages, genotypes, ff_values = get_freq_meta(rows)

    if not freq_bins:
        console.print("[red]Error: no frequency bin columns found in data file.[/red]")
        return 1

    console.print(f"\n[bold]pzfx_fill_frequency[/bold] — [dim]{args.data}[/dim]")
    console.print(f"[dim]Detected {len(freq_bins)} frequency bins ({freq_bins[-1]} – {freq_bins[0]} Hz)[/dim]")

    group_by = ask_group_by()

    if group_by == "stage":
        sel_genotypes = ask_selection("Select the Genotype", genotypes, single=True)
        sel_stages = ask_selection("Choose Stages", stages, single=False)
    else:
        sel_stages = ask_selection("Select the Stage", stages, single=True)
        sel_genotypes = ask_selection("Choose Genotypes", genotypes, single=False)

    if group_by == "stage":
        subgroup_col, subgroup_val = "Genotype", sel_genotypes[0]
        group_col_ff, group_vals_ff = "Stage", set(sel_stages)
    else:
        subgroup_col, subgroup_val = "Stage", sel_stages[0]
        group_col_ff, group_vals_ff = "Genotype", set(sel_genotypes)

    available_ff = sorted(
        {
            r.get("feature_for", "").strip()
            for r in rows
            if r.get(subgroup_col, "").strip() == subgroup_val
            and r.get(group_col_ff, "").strip() in group_vals_ff
        }
        - {""}
    )

    if not available_ff:
        console.print("[red]No feature_for values found for the selected combination.[/red]")
        return 1

    sel_feature_for = ask_selection("Select feature_for (table titles)", available_ff, single=False)

    n = build_pzfx_frequency(
        template_path=args.template,
        rows=rows,
        group_by=group_by,
        selected_stages=sel_stages,
        selected_genotypes=sel_genotypes,
        selected_feature_fors=sel_feature_for,
        output_path=args.output,
    )

    console.print(
        f"\n[bold green]Done.[/bold green] Written [cyan]{n}[/cyan] table(s) "
        f"(grouped by [cyan]{group_by}[/cyan]) "
        f"→ [bold]{args.output}[/bold]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
