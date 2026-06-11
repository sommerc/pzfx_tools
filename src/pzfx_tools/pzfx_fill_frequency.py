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
from rich.markup import escape
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


_REQUIRED_COLS = {"Stage", "Genotype"}


def _validate_input(path: str, rows: list[dict]) -> bool:
    """Check that a data file has the required metadata columns and frequency bins.

    Returns False if a fatal error was found."""
    cols = set(rows[0].keys())
    missing = _REQUIRED_COLS - cols
    if missing:
        console.print(
            f"[red]Error:[/red] [bold]{path}[/bold] — missing required column(s): "
            + ", ".join(sorted(missing))
        )
        return False
    freq_bins = [c for c in rows[0] if c not in META_COLS and _is_float(c)]
    if not freq_bins:
        console.print(
            f"[red]Error:[/red] [bold]{path}[/bold] — no frequency bin columns found "
            "(expected float-named columns such as '30.0', '25.8', …)."
        )
        return False
    return True


# ── interactive prompts ───────────────────────────────────────────────────────


def _print_numbered(title: str, items: list[str]) -> None:
    t = Table(title=title, show_header=False, box=None, padding=(0, 1))
    t.add_column("num", style="bold cyan", no_wrap=True)
    t.add_column("item", style="bright_white")
    for i, item in enumerate(items, 1):
        t.add_row(f"[{i}]", escape(item))
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


_BS_SUFFIX = " [bs]"
_JOINT_ORDER = ["shoulder", "elbow", "wrist", "hip", "knee", "ankle", "foot"]
_ARM_JOINTS = {"shoulder", "elbow", "wrist"}
_LEG_JOINTS = {"hip", "knee", "ankle", "foot"}


def _sort_display_items(items: list[str]) -> list[str]:
    def key(item: str) -> tuple:
        is_bs = item.endswith(_BS_SUFFIX)
        base = item[: -len(_BS_SUFFIX)] if is_bs else item
        limb = 0 if base in _ARM_JOINTS else (1 if base in _LEG_JOINTS else 2)
        within = _JOINT_ORDER.index(base) if base in _JOINT_ORDER else len(_JOINT_ORDER)
        return (0 if is_bs else 1, limb, within, item)
    return sorted(items, key=key)


def _detect_lr_pairs(ff_values: list[str]) -> dict[str, tuple[str, str]]:
    """Return {display_name: (left_ff, right_ff)} for every left_/right_ pair present."""
    result: dict[str, tuple[str, str]] = {}
    plain_left = {v[5:]: v for v in ff_values if v.startswith("left_")}
    plain_right = {v[6:]: v for v in ff_values if v.startswith("right_")}
    for base in plain_left:
        if base in plain_right:
            result[base] = (plain_left[base], plain_right[base])
    bs_left = {v[8:]: v for v in ff_values if v.startswith("bs_left_")}
    bs_right = {v[9:]: v for v in ff_values if v.startswith("bs_right_")}
    for base in bs_left:
        if base in bs_right:
            result[f"{base}{_BS_SUFFIX}"] = (bs_left[base], bs_right[base])
    return result


def _ff_display_name(ff: str) -> str:
    """Display name for a single ff value that belongs to a left/right pair."""
    if ff.startswith("bs_left_"):
        return f"{ff[8:]}{_BS_SUFFIX}"
    if ff.startswith("bs_right_"):
        return f"{ff[9:]}{_BS_SUFFIX}"
    if ff.startswith("left_"):
        return ff[5:]
    return ff[6:]  # right_


def ask_feature_fors_with_lr(
    available_ff: list[str],
) -> list[str | tuple[str, list[str]]]:
    """Prompt for feature_for selection, collapsing left_/right_ pairs into base names."""
    pairs = _detect_lr_pairs(available_ff)
    paired_raw = {v for lf, rf in pairs.values() for v in (lf, rf)}

    seen_displays: set[str] = set()
    display_items: list[str] = []
    bs_unpaired: dict[str, str] = {}  # display_name → raw ff value

    for ff in available_ff:
        if ff in paired_raw:
            display = _ff_display_name(ff)
            if display not in seen_displays:
                seen_displays.add(display)
                display_items.append(display)
        elif ff.startswith("bs_"):
            display = f"{ff[3:]}{_BS_SUFFIX}"
            bs_unpaired[display] = ff
            if display not in seen_displays:
                seen_displays.add(display)
                display_items.append(display)
        else:
            display_items.append(ff)

    display_items = _sort_display_items(display_items)
    selected = ask_selection("Select feature_for", display_items, single=False)

    result: list[str | tuple[str, list[str]]] = []
    selected_pairs = [item for item in selected if item in pairs]
    combine = False
    if selected_pairs:
        console.print()
        if len(selected_pairs) == 1:
            lf, rf = pairs[selected_pairs[0]]
            console.print(f"[bold cyan]{escape(selected_pairs[0])}[/bold cyan] has left/right variants ({lf} / {rf}):")
        else:
            console.print(f"[bold cyan]{len(selected_pairs)} selected joints[/bold cyan] have left/right variants:")
            for p in selected_pairs:
                lf, rf = pairs[p]
                console.print(f"  [dim]{escape(p)}[/dim]: {lf} / {rf}")
        console.print("  [bold cyan][1][/bold cyan] Separate columns for each")
        console.print("  [bold cyan][2][/bold cyan] Combine left and right  [dim](absolute values)[/dim]")
        while True:
            raw = Prompt.ask("[bold green]Selection[/bold green]", default="2")
            if raw.strip() == "1":
                combine = False
                break
            if raw.strip() == "2":
                combine = True
                break
            console.print("[red]Enter 1 or 2.[/red]")

    for item in selected:
        if item in pairs:
            left_ff, right_ff = pairs[item]
            if combine:
                result.append((item, [left_ff, right_ff]))
            else:
                result.append((item, [(left_ff, "left"), (right_ff, "right")]))
        elif item in bs_unpaired:
            result.append(bs_unpaired[item])
        else:
            result.append(item)
    return result


# ── pzfx builder ──────────────────────────────────────────────────────────────


def build_pzfx_frequency(
    template_path: str,
    rows: list[dict],
    group_by: str,
    selected_stages: list[str],
    selected_genotypes: list[str],
    selected_feature_fors: list[str | tuple[str, list[str]]],
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

    for ff_entry in ff_list:
        if ff_entry is None:
            ff_display: str | None = None
            ff_filter: list[str] | None = None
            ff_sides = None
        elif isinstance(ff_entry, tuple):
            ff_display = ff_entry[0]
            if ff_entry[1] and isinstance(ff_entry[1][0], str):
                ff_filter = list(ff_entry[1])
                ff_sides = None
            else:
                ff_filter = None
                ff_sides = list(ff_entry[1])  # [(ff_val, "left"/"right"), ...]
        else:
            ff_display = ff_entry
            ff_filter = [ff_entry]
            ff_sides = None

        table_id = f"Table{1000 + table_idx}"
        table_idx += 1

        if table_seq is not None:
            ET.SubElement(table_seq, "Ref").set("ID", table_id)

        if ff_sides is not None:
            max_reps = max(
                sum(
                    1 for r in rows
                    if r.get(group_col, "").strip() == g
                    and (not subgroup or r.get(subgroup_col, "").strip() == subgroup)
                    and r.get("feature_for", "").strip() == ff_val
                )
                for g in groups
                for ff_val, _ in ff_sides
            )
        else:
            max_reps = max(
                sum(
                    1
                    for r in rows
                    if r.get(group_col, "").strip() == g
                    and (not subgroup or r.get(subgroup_col, "").strip() == subgroup)
                    and (ff_filter is None or r.get("feature_for", "").strip() in ff_filter)
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

        title_text = ff_display if ff_display else "Frequency"
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

        if ff_sides is not None:
            # side-by-side: one YColumn per (group, side)
            for group in groups:
                for ff_val, side_label in ff_sides:
                    sub_rows = [
                        r for r in rows
                        if r.get(group_col, "").strip() == group
                        and (not subgroup or r.get(subgroup_col, "").strip() == subgroup)
                        and r.get("feature_for", "").strip() == ff_val
                    ]
                    if not sub_rows:
                        continue
                    n = len(sub_rows)
                    ycol = ET.SubElement(tbl_el, "YColumn")
                    ycol.set("Width", str(n * 109))
                    ycol.set("Decimals", "14")
                    ycol.set("Subcolumns", str(n))
                    ET.SubElement(ycol, "Title").text = f"{group} {side_label}"
                    for row in sub_rows:
                        sub_el = ET.SubElement(ycol, "Subcolumn")
                        for bin_col in freq_bins:
                            val = row.get(bin_col, "").strip()
                            ET.SubElement(sub_el, "d").text = val if val else None
        else:
            for group in groups:
                sub_rows = [
                    r
                    for r in rows
                    if r.get(group_col, "").strip() == group
                    and (not subgroup or r.get(subgroup_col, "").strip() == subgroup)
                    and (ff_filter is None or r.get("feature_for", "").strip() in ff_filter)
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

    if not _validate_input(args.data, rows):
        return 1

    freq_bins, stages, genotypes, _ = get_freq_meta(rows)

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

    sel_feature_for = ask_feature_fors_with_lr(available_ff)

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
