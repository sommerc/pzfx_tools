#!/usr/bin/env python3
"""Interactive GraphPad Prism .pzfx generator.

Prompts the user to choose:
  - Group tables by Stage or Genotype
  - Which features become YColumns
  - Which stages / genotypes to include

Usage:
  python pzfx_fill.py template.pzfx data.tab output.pzfx
  python pzfx_fill.py template.pzfx data1.tab data2.tab output.pzfx
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

# ── data helpers ──────────────────────────────────────────────────────────────

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


def get_meta(rows: list[dict]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Return (features, stages, genotypes, feature_for_values)."""
    if not rows:
        return [], [], [], []
    features = [c for c in rows[0] if c not in META_COLS and not _is_float(c)]
    stages = sorted({r.get("Stage", "").strip() for r in rows} - {""})
    genotypes = sorted({r.get("Genotype", "").strip() for r in rows} - {""})
    feature_for_values = sorted({r.get("feature_for", "").strip() for r in rows} - {""})
    return features, stages, genotypes, feature_for_values


_REQUIRED_COLS = {"Stage", "Genotype"}


def _validate_inputs(data_paths: list[str], all_file_rows: list[list[dict]]) -> bool:
    """Check each file for required columns and features; warn on cross-file inconsistencies.

    Returns False if any fatal error was found."""
    fatal = False
    for path, rows in zip(data_paths, all_file_rows):
        if not rows:
            continue
        cols = set(rows[0].keys())
        missing = _REQUIRED_COLS - cols
        if missing:
            console.print(
                f"[red]Error:[/red] [bold]{path}[/bold] — missing required column(s): "
                + ", ".join(sorted(missing))
            )
            fatal = True
        features = [c for c in rows[0] if c not in META_COLS and not _is_float(c)]
        if not features:
            console.print(
                f"[red]Error:[/red] [bold]{path}[/bold] — no feature columns found."
            )
            fatal = True

    if fatal:
        return False

    non_empty = [(p, r) for p, r in zip(data_paths, all_file_rows) if r]
    if len(non_empty) > 1:
        has_ff = [
            any(r.get("feature_for", "").strip() for r in rows)
            for _, rows in non_empty
        ]
        if any(has_ff) and not all(has_ff):
            without = [p for (p, _), hf in zip(non_empty, has_ff) if not hf]
            console.print(
                "[yellow]Warning:[/yellow] 'feature_for' column absent or empty in: "
                + ", ".join(without)
            )

    return True


# ── interactive prompts ───────────────────────────────────────────────────────


def _print_numbered(title: str, items: list[str]) -> None:
    t = Table(title=title, show_header=False, box=None, padding=(0, 1))
    t.add_column("num", style="bold cyan", no_wrap=True)
    t.add_column("item", style="bright_white")
    for i, item in enumerate(items, 1):
        t.add_row(f"[{i}]", escape(item))
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
        console.print("  [bold cyan][2][/bold cyan] Negate one side and combine  [dim](right side negated)[/dim]")
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


def _init_tree(template_path: str):
    """Parse template, strip existing tables; return (tree, root, table_seq)."""
    ET.register_namespace("dt", "urn:schemas-microsoft-com:datatypes")
    tree = ET.parse(template_path)
    root = tree.getroot()
    table_seq = root.find("TableSequence")
    if table_seq is not None:
        for ref in list(table_seq):
            table_seq.remove(ref)
    for table in root.findall("Table"):
        root.remove(table)
    return tree, root, table_seq


def _append_tables(
    root,
    table_seq,
    rows: list[dict],
    group_by: str,
    selected_features: list[str],
    selected_stages: list[str],
    selected_genotypes: list[str],
    selected_feature_fors: list[str | tuple[str, list[str]]],
    table_idx_start: int = 0,
) -> int:
    """Append OneWay tables to root; return the next available table_idx."""
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

    ff_list = selected_feature_fors if selected_feature_fors else [None]
    table_idx = table_idx_start
    for feature in selected_features:
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

            # ── YColumns ──
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
                        values = [r.get(feature, "").strip() for r in sub_rows]
                        if not any(values):
                            continue
                        ycol_el = ET.SubElement(table_el, "YColumn")
                        ycol_el.set("Width", "81")
                        ycol_el.set("Decimals", "14")
                        ycol_el.set("Subcolumns", "1")
                        ET.SubElement(ycol_el, "Title").text = f"{group} {side_label}"
                        sub_el = ET.SubElement(ycol_el, "Subcolumn")
                        for val in values:
                            ET.SubElement(sub_el, "d").text = val if val else None
            else:
                # one YColumn per group
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

                    # When combining left+right, negate the right side to align
                    # mirror-convention angle measurements before pooling.
                    right_ff = ff_filter[1] if ff_filter and len(ff_filter) > 1 else None
                    for r in sub_rows:
                        val = r.get(feature, "").strip()
                        if val and right_ff and r.get("feature_for", "").strip() == right_ff:
                            try:
                                val = str(-float(val))
                            except ValueError:
                                pass
                        d_el = ET.SubElement(sub_el, "d")
                        d_el.text = val if val else None

    return table_idx


def build_pzfx(
    template_path: str,
    rows: list[dict],
    group_by: str,
    selected_features: list[str],
    selected_stages: list[str],
    selected_genotypes: list[str],
    selected_feature_fors: list[str | tuple[str, list[str]]],
    output_path: str,
) -> int:
    """Build the .pzfx file and return the number of tables written."""
    tree, root, table_seq = _init_tree(template_path)
    table_idx = _append_tables(
        root, table_seq, rows, group_by,
        selected_features, selected_stages, selected_genotypes, selected_feature_fors,
    )
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
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="One or more data .tab files, followed by the output .pzfx path",
    )
    args = parser.parse_args()

    if len(args.files) < 2:
        parser.error("Provide at least one data file and an output path")
    data_paths, output_path = args.files[:-1], args.files[-1]

    # Load all files; keep per-file rows separate for per-file prompts
    all_file_rows: list[list[dict]] = []
    for path in data_paths:
        file_rows = read_tab(path)
        if not file_rows:
            console.print(f"[yellow]Warning: {path} is empty, skipping.[/yellow]")
            all_file_rows.append([])
        else:
            all_file_rows.append(file_rows)

    if not _validate_inputs(data_paths, all_file_rows):
        return 1

    # Combined pool for global stage/genotype prompts
    combined_rows = [r for file_rows in all_file_rows for r in file_rows]
    if not combined_rows:
        console.print("[red]Error: all data files are empty.[/red]")
        return 1

    _, all_stages, all_genotypes, _ = get_meta(combined_rows)

    data_label = ", ".join(data_paths)
    console.print(f"\n[bold]pzfx_fill[/bold] — [dim]{data_label}[/dim]")

    # ── global prompts (shared across all files) ──
    group_by = ask_group_by()

    if group_by == "stage":
        sel_genotypes = ask_selection("Select the Genotype", all_genotypes, single=True)
        sel_stages = ask_selection("Choose Stages", all_stages, single=False)
    else:
        sel_stages = ask_selection("Select the Stage", all_stages, single=True)
        sel_genotypes = ask_selection("Choose Genotypes", all_genotypes, single=False)

    # ── per-file prompts + table building ──
    tree, root, table_seq = _init_tree(args.template)
    table_idx = 0
    multi = len(data_paths) > 1

    for i, (path, file_rows) in enumerate(zip(data_paths, all_file_rows)):
        if not file_rows:
            continue

        if multi:
            console.print(f"\n[bold cyan]── File {i + 1}/{len(data_paths)}: [/bold cyan][dim]{path}[/dim]")

        features, _, _, feature_for_values = get_meta(file_rows)

        if not features:
            console.print(f"[yellow]Warning: no feature columns in {path}, skipping.[/yellow]")
            continue

        sel_feature_for: list[str] = []
        if feature_for_values:
            if group_by == "stage":
                subgroup_col, subgroup_val = "Genotype", sel_genotypes[0]
                group_col_ff, group_vals_ff = "Stage", set(sel_stages)
            else:
                subgroup_col, subgroup_val = "Stage", sel_stages[0]
                group_col_ff, group_vals_ff = "Genotype", set(sel_genotypes)
            available_ff = sorted(
                {r.get("feature_for", "").strip() for r in file_rows
                 if r.get(subgroup_col, "").strip() == subgroup_val
                 and r.get(group_col_ff, "").strip() in group_vals_ff}
                - {""}
            )
            if available_ff:
                sel_feature_for = ask_feature_fors_with_lr(available_ff)
            else:
                console.print("[yellow]No feature_for values found for the selected stage/genotype combination.[/yellow]")

        sel_features = ask_selection("Features (YColumns)", features, single=False)

        table_idx = _append_tables(
            root, table_seq, file_rows, group_by,
            sel_features, sel_stages, sel_genotypes, sel_feature_for,
            table_idx_start=table_idx,
        )

    if table_idx == 0:
        console.print("[red]No tables were produced — check your selections.[/red]")
        return 1

    ET.indent(root, space="\t")
    tree.write(output_path, encoding="unicode", xml_declaration=True)

    console.print(
        f"\n[bold green]Done.[/bold green] Written [cyan]{table_idx}[/cyan] table(s) "
        f"(grouped by [cyan]{group_by}[/cyan]) "
        f"→ [bold]{output_path}[/bold]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
