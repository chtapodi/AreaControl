#!/usr/bin/env python3
"""
Validate the YAML configs consumed by area_tree without needing Home Assistant.

Checks are focused on layout/devices/connections to spot missing references,
type mismatches, and structural issues that would surface at runtime.
"""

import argparse
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Set, Tuple

import yaml

DEFAULT_CONFIG = {
    "layout": "./pyscript/layout.yml",
    "devices": "./pyscript/devices.yml",
    "connections": "./pyscript/connections.yml",
}

SUPPORTED_DEVICE_TYPES = {
    "light",
    "blind",
    "speaker",
    "plug",
    "contact_sensor",
    "fan",
    "television",
}


def normalize_category(msg: str) -> str:
    """Group similar findings by stripping leading name and collapsing quoted content."""
    if ":" in msg:
        msg = msg.split(":", 1)[1].strip()
    msg = re.sub(r"'[^']+'", "'{name}'", msg)
    msg = re.sub(r'"[^"]+"', '"{name}"', msg)
    msg = re.sub(r"\[[^\]]+\]", "[{list}]", msg)
    return msg


@dataclass
class Finding:
    severity: str
    section: str
    message: str


class DiagnosticsReport:
    def __init__(self):
        self.sections: Dict[str, List[Finding]] = defaultdict(list)

    def add(self, section: str, severity: str, message: str):
        self.sections[section].append(Finding(severity, section, message))

    def has_errors(self) -> bool:
        return any(f.severity == "error" for f in self._all())

    def _all(self) -> Iterable[Finding]:
        for findings in self.sections.values():
            for finding in findings:
                yield finding

    def render(self, color: bool = False, areas: Set[str] = None, devices: Set[str] = None) -> str:
        areas = areas or set()
        devices = devices or set()

        def style(text: str, code: str) -> str:
            return f"\033[{code}m{text}\033[0m" if color else text

        def color_name(name: str) -> str:
            if not color:
                return name
            if name in devices:
                return style(name, "35;1")  # bold magenta for devices
            if name in areas:
                return style(name, "36;1")  # bold cyan for areas
            return style(name, "36")  # default cyan-ish

        def highlight_names(text: str) -> str:
            """Color substrings in quotes and leading area/device prefixes."""
            if not color:
                return text

            # Highlight leading prefix before colon if it looks like a name
            prefix_match = re.match(r"([^:]+):\s*(.*)", text)
            if prefix_match:
                prefix, rest = prefix_match.groups()
                colored_prefix = color_name(prefix) if prefix in areas or prefix in devices else prefix
                text = f"{colored_prefix}: {rest}"

            # Highlight anything wrapped in single or double quotes
            def _replace(match):
                raw = match.group(0)
                name = raw.strip("'\"")
                return raw.replace(name, color_name(name))

            text = re.sub(r"'[^']+'", _replace, text)
            text = re.sub(r'"[^"]+"', _replace, text)

            # Highlight bare names if they exactly match known areas/devices
            for name in sorted(areas | devices, key=len, reverse=True):
                text = re.sub(fr"\b{name}\b", color_name(name), text)
            return text

        severities = {
            "error": ("ERROR", "31;1"),  # bold red
            "warning": ("WARN", "33;1"),  # bold yellow
            "info": ("INFO", "36"),  # cyan
        }

        lines: List[str] = []
        severity_rank = {"error": 0, "warning": 1, "info": 2}
        for section in ("layout", "devices", "connections"):
            raw_findings = self.sections.get(section, [])
            findings = sorted(
                raw_findings,
                key=lambda f: (severity_rank.get(f.severity, 99), f.message.lower()),
            )
            errs = sum(1 for f in findings if f.severity == "error")
            warns = sum(1 for f in findings if f.severity == "warning")
            infos = sum(1 for f in findings if f.severity == "info")
            header = f"{section.capitalize():<11} {errs} error(s), {warns} warning(s), {infos} info"
            lines.append(style(header, "1"))  # bold section header

            grouped: Dict[str, Dict[str, List[Finding]]] = defaultdict(lambda: defaultdict(list))
            for finding in findings:
                cat = normalize_category(finding.message)
                grouped[finding.severity][cat].append(finding)

            for severity in ("error", "warning", "info"):
                severity_findings = grouped.get(severity)
                if not severity_findings:
                    continue
                label, code = severities.get(severity, ("INFO", "36"))
                first_category = True
                for category in sorted(severity_findings.keys()):
                    items = sorted(severity_findings[category], key=lambda f: f.message.lower())
                    if not first_category:
                        lines.append("")  # gap between categories for readability
                    first_category = False
                    lines.append(
                        f"  [{style(label, code)}] {category} ({len(items)})"
                    )
                    for item in items:
                        message = highlight_names(item.message)
                        lines.append(f"    - {message}")
            if findings:
                lines.append("")  # spacer between sections
        overall = "FAIL" if self.has_errors() else "PASS"
        lines.append(style(f"Overall: {overall}", "32;1" if overall == "PASS" else "31;1"))
        return "\n".join(lines)


def _load_yaml_file(path: str, section: str, report: DiagnosticsReport):
    if not path:
        report.add(section, "error", f"No path provided for {section}")
        return {}
    expanded = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(expanded):
        report.add(section, "error", f"{section} file not found: {expanded}")
        return {}
    try:
        with open(expanded, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception as exc:  # pragma: no cover - defensive for broken configs
        report.add(section, "error", f"Failed to load {expanded}: {exc}")
        return {}


def _resolve_paths(args) -> Dict[str, str]:
    paths = dict(DEFAULT_CONFIG)
    config_path = os.path.abspath(os.path.expanduser(args.config))
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                cfg = yaml.safe_load(handle) or {}
            config_paths = cfg.get("paths", cfg)
            if isinstance(config_paths, dict):
                for key, value in config_paths.items():
                    if value:
                        paths[key] = value
        except Exception:
            # Keep defaults if config cannot be parsed
            pass

    if args.layout:
        paths["layout"] = args.layout
    if args.devices:
        paths["devices"] = args.devices
    if args.connections:
        paths["connections"] = args.connections
    return {k: os.path.abspath(os.path.expanduser(v)) for k, v in paths.items()}


def _coerce_list(value, area_name: str, field: str, section: str, report: DiagnosticsReport):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    report.add(
        section,
        "warning",
        f"{area_name}: '{field}' should be a list; found {type(value).__name__}, ignoring",
    )
    return []


def _detect_cycles(children: Dict[str, Set[str]]) -> List[Tuple[str, List[str]]]:
    cycles: List[Tuple[str, List[str]]] = []
    visited: Set[str] = set()
    stack: Set[str] = set()

    def dfs(node: str, path: List[str]):
        visited.add(node)
        stack.add(node)
        for child in children.get(node, set()):
            if child not in visited:
                dfs(child, path + [child])
            elif child in stack:
                start_index = path.index(child) if child in path else 0
                cycles.append((child, path[start_index:] + [child]))
        stack.discard(node)

    for node in children:
        if node not in visited:
            dfs(node, [node])
    return cycles


def validate_layout(layout_data, devices_data, report: DiagnosticsReport):
    area_defs: Set[str] = set()
    referenced_children: Set[str] = set()
    parents: Dict[str, List[str]] = defaultdict(list)
    children: Dict[str, Set[str]] = defaultdict(set)
    output_usage: Dict[str, List[str]] = defaultdict(list)

    if not isinstance(layout_data, dict):
        report.add("layout", "error", "Layout must be a mapping of area name -> config block")
        return area_defs, referenced_children, output_usage, children, parents

    area_defs.update(layout_data.keys())

    for area_name, cfg in layout_data.items():
        if cfg is None:
            report.add("layout", "warning", f"{area_name}: has no configuration block")
            cfg = {}
        if not isinstance(cfg, dict):
            report.add(
                "layout",
                "error",
                f"{area_name}: config is {type(cfg).__name__}, expected a mapping; skipping deeper checks",
            )
            continue

        sub_areas = _coerce_list(cfg.get("sub_areas"), area_name, "sub_areas", "layout", report)
        direct_sub_areas = _coerce_list(
            cfg.get("direct_sub_areas"), area_name, "direct_sub_areas", "layout", report
        )
        for child in sub_areas + direct_sub_areas:
            if child is None or child == "":
                report.add("layout", "warning", f"{area_name}: contains an empty sub-area entry")
                continue
            parents[child].append(area_name)
            children[area_name].add(child)
            referenced_children.add(child)
            if child not in area_defs:
                report.add(
                    "layout",
                    "warning",
                    f"{area_name}: references sub-area '{child}' that is not defined elsewhere",
                )

        outputs = cfg.get("outputs")
        if outputs is not None:
            if not isinstance(outputs, list):
                report.add(
                    "layout",
                    "warning",
                    f"{area_name}: outputs should be a list; found {type(outputs).__name__}",
                )
            else:
                for output in outputs:
                    if output is None or output == "":
                        report.add("layout", "warning", f"{area_name}: outputs contains an empty entry")
                        continue
                    output_usage[output].append(area_name)
                    if isinstance(devices_data, dict) and output not in devices_data:
                        report.add(
                            "layout",
                            "error",
                            f"{area_name}: output '{output}' missing from devices.yml",
                        )

        inputs = cfg.get("inputs")
        if inputs is not None:
            if isinstance(inputs, dict):
                for input_type, device_ids in inputs.items():
                    if device_ids is None:
                        report.add(
                            "layout",
                            "warning",
                            f"{area_name}: input type '{input_type}' has no devices listed",
                        )
                        continue
                    if not isinstance(device_ids, list):
                        report.add(
                            "layout",
                            "warning",
                            f"{area_name}: input type '{input_type}' should list devices; found {type(device_ids).__name__}",
                        )
                        continue
                    for device_id in device_ids:
                        if device_id is None or device_id == "":
                            report.add(
                                "layout",
                                "warning",
                                f"{area_name}: input type '{input_type}' contains an empty device id",
                            )
            elif isinstance(inputs, list):
                report.add(
                    "layout",
                    "warning",
                    f"{area_name}: inputs is a list; area_tree ignores list-form inputs",
                )
            else:
                report.add(
                    "layout",
                    "warning",
                    f"{area_name}: inputs should be a dict of input_type -> list; found {type(inputs).__name__}",
                )

    for child, parent_list in parents.items():
        if len(parent_list) > 1:
            report.add(
                "layout",
                "warning",
                f"{child}: attached to multiple parents {sorted(set(parent_list))}; only the last one will stick",
            )

    for output, areas in output_usage.items():
        if len(set(areas)) > 1:
            report.add(
                "layout",
                "warning",
                f"Output '{output}' is assigned to multiple areas {sorted(set(areas))}",
            )

    roots = [area for area in area_defs if area not in parents]
    if not roots:
        report.add(
            "layout",
            "error",
            "No root area detected (every area has a parent). Check for accidental cycles or missing top-level area.",
        )
    elif len(roots) > 1:
        report.add("layout", "warning", f"Multiple roots detected: {sorted(roots)}")

    cycles = _detect_cycles(children)
    for anchor, path in cycles:
        report.add("layout", "error", f"Cycle detected involving {anchor}: {' -> '.join(path)}")

    reachable = set()
    for root in roots:
        stack = [root]
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            stack.extend(children.get(node, []))
    disconnected = area_defs - reachable
    if disconnected:
        report.add(
            "layout",
            "warning",
            f"Areas defined but not reachable from any root: {sorted(disconnected)}",
        )

    return area_defs, referenced_children, output_usage, children, parents


def validate_devices(devices_data, outputs_in_layout: Set[str], report: DiagnosticsReport):
    if not isinstance(devices_data, dict):
        report.add("devices", "error", "Devices file must be a mapping of device name -> config block")
        return

    for device_name, cfg in devices_data.items():
        if cfg is None:
            report.add("devices", "warning", f"{device_name}: has no configuration block")
            continue
        if not isinstance(cfg, dict):
            report.add(
                "devices",
                "error",
                f"{device_name}: config is {type(cfg).__name__}, expected a mapping",
            )
            continue

        dtype = cfg.get("type")
        if dtype is None:
            report.add(
                "devices",
                "warning",
                f"{device_name}: has no 'type'; area_tree will fall back to name-based heuristics",
            )
        elif dtype not in SUPPORTED_DEVICE_TYPES:
            report.add(
                "devices",
                "warning",
                f"{device_name}: unsupported type '{dtype}' (expected one of {sorted(SUPPORTED_DEVICE_TYPES)})",
            )

        filters = cfg.get("filters")
        if filters is not None and not isinstance(filters, list):
            report.add(
                "devices",
                "warning",
                f"{device_name}: filters should be a list; found {type(filters).__name__}",
            )

    unused = set(devices_data.keys()) - set(outputs_in_layout)
    if unused:
        sample = sorted(unused)
        preview = sample if len(sample) <= 6 else sample[:6] + ["..."]
        report.add(
            "devices",
            "info",
            f"{len(unused)} device(s) are not referenced in layout outputs: {preview}",
        )


def validate_connections(connections_data, known_areas: Set[str], report: DiagnosticsReport):
    if not isinstance(connections_data, dict):
        report.add("connections", "error", "Connections file must be a mapping with a 'connections' list")
        return

    entries = connections_data.get("connections")
    if entries is None:
        report.add("connections", "error", "Missing 'connections' key")
        return
    if not isinstance(entries, list):
        report.add(
            "connections",
            "error",
            f"'connections' should be a list of area pairs; found {type(entries).__name__}",
        )
        return

    seen_edges: Set[Tuple[str, str]] = set()

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            report.add(
                "connections",
                "warning",
                f"Entry #{idx + 1} should be a mapping like '- area_a: area_b'; found {type(entry).__name__}",
            )
            continue

        if len(entry.items()) != 1:
            report.add(
                "connections",
                "warning",
                f"Entry #{idx + 1} should contain exactly one pair; found {len(entry.items())}",
            )

        for start, end in entry.items():
            if start is None or end is None or start == "" or end == "":
                report.add("connections", "warning", f"Entry #{idx + 1} has an empty area name")
                continue

            if start not in known_areas:
                report.add(
                    "connections",
                    "warning",
                    f"Entry #{idx + 1}: '{start}' is not defined in layout",
                )
            if end not in known_areas:
                report.add(
                    "connections",
                    "warning",
                    f"Entry #{idx + 1}: '{end}' is not defined in layout",
                )

            normalized = tuple(sorted((start, end)))
            if normalized in seen_edges:
                report.add(
                    "connections",
                    "info",
                    f"Entry #{idx + 1}: duplicate connection between {start} and {end}",
                )
            seen_edges.add(normalized)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate layout/devices/connections configs used by area_tree"
    )
    parser.add_argument(
        "--config",
        default="./pyscript/config.yml",
        help="Path to central config.yml (used to resolve other paths)",
    )
    parser.add_argument("--layout", help="Override layout.yml path")
    parser.add_argument("--devices", help="Override devices.yml path")
    parser.add_argument("--connections", help="Override connections.yml path")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color output (auto-disabled when stdout is not a TTY)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    paths = _resolve_paths(args)
    report = DiagnosticsReport()

    layout_data = _load_yaml_file(paths["layout"], "layout", report)
    devices_data = _load_yaml_file(paths["devices"], "devices", report)
    connections_data = _load_yaml_file(paths["connections"], "connections", report)

    area_defs, referenced_children, output_usage, children, parents = validate_layout(
        layout_data, devices_data, report
    )
    outputs_in_layout = set(output_usage.keys())
    known_areas = set(area_defs | referenced_children)

    validate_devices(devices_data, outputs_in_layout, report)
    validate_connections(connections_data, known_areas, report)

    color_enabled = not args.no_color and os.isatty(1)
    known_devices = set(devices_data.keys()) if isinstance(devices_data, dict) else set()
    print(report.render(color=color_enabled, areas=known_areas, devices=known_devices))
    return 1 if report.has_errors() else 0


if __name__ == "__main__":
    raise SystemExit(main())
