"""Gutterline: an offline gutter and downspout planner driven by a plain-text job file.

Each roof plane drains onto one gutter run. Design flow uses the rational
method, Q = i * A / 3600 (L/s, with i in mm/h and A in m^2), with exact
fractions. Gutter capacity uses Manning's equation for a full section.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

STANDARD_ROUND_MM = (100, 125, 150, 175)
SINGLE_DIRECTIVES = (
    "rain", "fall", "roughness", "hanger", "stock",
    "max-spacing", "limit", "gutter", "downspout",
)


@dataclass
class Issue:
    line: int
    level: str
    message: str


@dataclass
class Gutter:
    profile: str
    dims_mm: tuple
    price: Fraction

    def label(self):
        return f"{self.profile} {' x '.join(plain(d) for d in self.dims_mm)} mm"

    def section(self):
        """Full-section flow area (m^2) and wetted perimeter (m)."""
        if self.profile == "round":
            d = float(self.dims_mm[0]) / 1000
            return math.pi * d * d / 8, math.pi * d / 2 + d
        width, height = (float(x) / 1000 for x in self.dims_mm)
        return width * height, width + 2 * height

    def capacity_lps(self, fall_n, roughness):
        """Manning full-section capacity in L/s for a fall of 1:fall_n."""
        area, wetted = self.section()
        radius = area / wetted
        slope = 1 / float(fall_n)
        flow_m3s = area * radius ** (2 / 3) * math.sqrt(slope) / float(roughness)
        return flow_m3s * 1000


@dataclass
class Downspout:
    diameter_mm: Fraction
    capacity: Fraction
    price: Fraction


@dataclass
class Plane:
    name: str
    length: Fraction
    run: Fraction
    line: int


@dataclass
class Job:
    rain: Fraction | None = None
    fall_n: Fraction = Fraction(200)
    roughness: Fraction = Fraction(12, 1000)
    hanger: Fraction = Fraction(6, 10)
    stock: Fraction = Fraction(3)
    max_spacing: Fraction = Fraction(12)
    limit: Fraction = Fraction(4, 5)
    gutter: Gutter | None = None
    downspout: Downspout | None = None
    planes: list = field(default_factory=list)


@dataclass
class Row:
    plane: str
    length: Fraction
    run: Fraction
    area: Fraction
    flow: Fraction
    capacity: float
    use: float
    status: str
    outlets: int
    spacing: Fraction
    hangers: int
    pieces: int
    joints: int
    gutter_cost: Fraction
    downspout_cost: Fraction


def plain(value):
    """Show a fraction as a clean number: 125 rather than 125/1, 0.6 rather than 3/5."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{float(value):g}"


def money(amount):
    """Round an exact amount to cents, half up."""
    exact = Decimal(amount.numerator) / Decimal(amount.denominator)
    return str(exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _number(text, what):
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{what} must be a number, got '{text}'") from None


def _positive(text, what):
    value = _number(text, what)
    if value <= 0:
        raise ValueError(f"{what} must be greater than zero, got '{text}'")
    return value


def _single(args, usage):
    if len(args) != 1:
        raise ValueError(f"expected: {usage}")
    return args[0]


def _split_options(args, allowed):
    positional, options = [], {}
    for token in args:
        if "=" in token:
            key, _, value = token.partition("=")
            if key not in allowed or not value:
                raise ValueError(f"unknown option '{token}'")
            options[key] = value
        else:
            positional.append(token)
    return positional, options


def _fall(text):
    left, sep, right = text.partition(":")
    if sep != ":" or left != "1":
        raise ValueError(f"fall must look like 1:200, got '{text}'")
    return _positive(right, "fall ratio")


def _gutter(args):
    positional, options = _split_options(args, {"price"})
    if "price" not in options:
        raise ValueError("gutter needs price=AMOUNT per metre")
    if not positional:
        raise ValueError("gutter needs a profile: 'round D' or 'box W H'")
    profile, sizes = positional[0].lower(), positional[1:]
    if (profile, len(sizes)) not in (("round", 1), ("box", 2)):
        raise ValueError("gutter round needs one size in mm; box needs width and height in mm")
    dims = tuple(_positive(s, "gutter size") for s in sizes)
    return Gutter(profile, dims, _positive(options["price"], "price"))


def _downspout(args):
    positional, options = _split_options(args, {"capacity", "price"})
    if len(positional) != 1 or "capacity" not in options or "price" not in options:
        raise ValueError("downspout needs DIAMETER_MM capacity=L_PER_S price=AMOUNT")
    return Downspout(
        _positive(positional[0], "downspout diameter"),
        _positive(options["capacity"], "capacity"),
        _positive(options["price"], "price"),
    )


def _apply(job, keyword, args, lineno, issues):
    if keyword == "rain":
        job.rain = _positive(_single(args, "rain MM_PER_H"), "rain")
    elif keyword == "fall":
        job.fall_n = _fall(_single(args, "fall 1:N"))
        if job.fall_n > 500:
            issues.append(Issue(lineno, "warning", f"fall 1:{plain(job.fall_n)} is flatter than 1:500; water may pond"))
        elif job.fall_n < 50:
            issues.append(Issue(lineno, "warning", f"fall 1:{plain(job.fall_n)} is steeper than 1:50; gutter will look wrong"))
    elif keyword == "roughness":
        job.roughness = _positive(_single(args, "roughness N"), "roughness")
    elif keyword == "hanger":
        job.hanger = _positive(_single(args, "hanger M"), "hanger spacing")
    elif keyword == "stock":
        job.stock = _positive(_single(args, "stock M"), "stock length")
    elif keyword == "max-spacing":
        job.max_spacing = _positive(_single(args, "max-spacing M"), "max-spacing")
    elif keyword == "limit":
        job.limit = _positive(_single(args, "limit FRACTION"), "limit")
        if job.limit > 1:
            raise ValueError("limit must be at most 1 (100%)")
    elif keyword == "gutter":
        job.gutter = _gutter(args)
    elif keyword == "downspout":
        job.downspout = _downspout(args)
    elif keyword == "plane":
        if len(args) != 3:
            raise ValueError("expected: plane NAME LENGTH_M RUN_M")
        name = args[0]
        if any(p.name == name for p in job.planes):
            raise ValueError(f"duplicate plane '{name}'")
        job.planes.append(Plane(name, _positive(args[1], "plane length"),
                                _positive(args[2], "plane run"), lineno))
    else:
        raise ValueError(f"unknown directive '{keyword}'")


def parse_job(text, rain=None):
    """Parse a job file. Returns (Job, issues); errors make the job unusable."""
    job = Job()
    issues = []
    first_line = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        words = raw.split("#", 1)[0].split()
        if not words:
            continue
        keyword, args = words[0].lower(), words[1:]
        try:
            if keyword in SINGLE_DIRECTIVES:
                if keyword in first_line:
                    raise ValueError(f"duplicate '{keyword}' (first set on line {first_line[keyword]})")
                first_line[keyword] = lineno
            _apply(job, keyword, args, lineno, issues)
        except ValueError as exc:
            issues.append(Issue(lineno, "error", str(exc)))
    if rain is not None:
        job.rain = rain
    if job.rain is None:
        issues.append(Issue(0, "error", "missing 'rain' (design rainfall in mm/h)"))
    if job.gutter is None:
        issues.append(Issue(0, "error", "missing 'gutter' line"))
    if job.downspout is None:
        issues.append(Issue(0, "error", "missing 'downspout' line"))
    if not job.planes:
        issues.append(Issue(0, "error", "no 'plane' lines"))
    return job, issues


def status_for(use, limit):
    if use > 1:
        return "OVER"
    if use > limit:
        return "TIGHT"
    return "OK"


def analyse(job, gutter=None):
    """One row per roof plane: flow, capacity, outlets, stock pieces and costs."""
    gutter = gutter or job.gutter
    capacity = gutter.capacity_lps(job.fall_n, job.roughness)
    ds = job.downspout
    rows = []
    for plane in job.planes:
        area = plane.length * plane.run
        flow = job.rain * area / 3600
        use = float(flow) / capacity
        outlets = max(1, math.ceil(flow / ds.capacity), math.ceil(plane.length / job.max_spacing))
        pieces = math.ceil(plane.length / job.stock)
        rows.append(Row(
            plane=plane.name,
            length=plane.length,
            run=plane.run,
            area=area,
            flow=flow,
            capacity=capacity,
            use=use,
            status=status_for(use, float(job.limit)),
            outlets=outlets,
            spacing=plane.length / outlets,
            hangers=math.ceil(plane.length / job.hanger) + 1,
            pieces=pieces,
            joints=pieces - 1,
            gutter_cost=pieces * job.stock * gutter.price,
            downspout_cost=outlets * ds.price,
        ))
    return rows


def pick_round_size(job):
    """Smallest standard round gutter where every plane stays within the limit."""
    for size in STANDARD_ROUND_MM:
        candidate = Gutter("round", (Fraction(size),), job.gutter.price)
        rows = analyse(job, candidate)
        if all(row.status == "OK" for row in rows):
            return size, rows
    return None, None


def render_report(path, job, rows):
    ds = job.downspout
    lines = [
        f"Gutterline report: {path}",
        f"Rain {plain(job.rain)} mm/h | fall 1:{plain(job.fall_n)} | Manning n {float(job.roughness):g} "
        f"| gutter {job.gutter.label()} | limit {float(job.limit) * 100:.0f}%",
        f"Downspout {plain(ds.diameter_mm)} mm, {plain(ds.capacity)} L/s each | "
        f"stock {plain(job.stock)} m | hangers every {plain(job.hanger)} m | max spacing {plain(job.max_spacing)} m",
        "",
        f"{'Plane':<10}{'Length':>8}{'Run':>7}{'Area m2':>10}{'Flow L/s':>10}{'Cap L/s':>9}{'Use':>7}  Status",
    ]
    for r in rows:
        lines.append(
            f"{r.plane:<10}{float(r.length):>8.2f}{float(r.run):>7.2f}{float(r.area):>10.2f}"
            f"{float(r.flow):>10.3f}{r.capacity:>9.3f}{r.use * 100:>6.1f}%  {r.status}"
        )
    lines += [
        "",
        f"{'Plane':<10}{'Outlets':>8}{'Spacing m':>11}{'Hangers':>9}{'Pieces':>8}{'Joints':>8}"
        f"{'Gutter':>12}{'Downspouts':>12}",
    ]
    for r in rows:
        lines.append(
            f"{r.plane:<10}{r.outlets:>8}{float(r.spacing):>11.2f}{r.hangers:>9}{r.pieces:>8}{r.joints:>8}"
            f"{money(r.gutter_cost):>12}{money(r.downspout_cost):>12}"
        )
    total_area = sum(r.area for r in rows)
    total_cost = sum((r.gutter_cost + r.downspout_cost for r in rows), Fraction(0))
    lines += [
        "",
        f"Roof area {float(total_area):.2f} m2 | design flow {float(sum(r.flow for r in rows)):.3f} L/s "
        f"| outlets {sum(r.outlets for r in rows)} | total cost {money(total_cost)}",
    ]
    for r in rows:
        if r.status != "OK":
            lines.append(f"  {r.status}: {r.plane} runs at {r.use * 100:.1f}% of gutter capacity")
    return "\n".join(lines)


def format_issue(path, issue):
    where = f"{path}:{issue.line}" if issue.line else str(path)
    return f"{where}: {issue.level}: {issue.message}"


def _load(path, rain):
    text = Path(path).read_text(encoding="utf-8")
    return parse_job(text, rain=rain)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gutterline", description="Offline gutter and downspout planner.")
    sub = parser.add_subparsers(dest="command", required=True)
    help_text = {
        "report": "print the full drainage, outlet, stock and cost report",
        "lint": "check the job file and print line-numbered issues",
        "pick": "find the smallest standard round gutter that fits every plane",
        "check": "CI gate: exit 1 if any plane overflows, 2 if the file is invalid",
    }
    for name, text in help_text.items():
        p = sub.add_parser(name, help=text)
        p.add_argument("file", help="plain-text job file")
        if name != "lint":
            p.add_argument("--rain", metavar="MM_PER_H", help="override the design rainfall for a what-if")
        if name == "check":
            p.add_argument("--strict", action="store_true", help="also fail on TIGHT planes")
    args = parser.parse_args(argv)

    rain = None
    if getattr(args, "rain", None) is not None:
        try:
            rain = _positive(args.rain, "--rain")
        except ValueError as exc:
            print(f"gutterline: {exc}", file=sys.stderr)
            return 2
    try:
        job, issues = _load(args.file, rain)
    except OSError as exc:
        print(f"gutterline: cannot read {args.file}: {exc.strerror}", file=sys.stderr)
        return 2

    for issue in issues:
        print(format_issue(args.file, issue), file=sys.stderr if args.command != "lint" else sys.stdout)
    has_errors = any(i.level == "error" for i in issues)

    if args.command == "lint":
        if not issues:
            print(f"{args.file}: no issues found")
        return 2 if has_errors else 0
    if has_errors:
        return 2

    if args.command == "report":
        print(render_report(args.file, job, analyse(job)))
        return 0

    if args.command == "pick":
        size, rows = pick_round_size(job)
        if size is None:
            print("no standard round gutter keeps every plane within the limit; try a box gutter or more downspouts")
            return 1
        print(f"smallest standard round gutter: {size} mm")
        return 0

    rows = analyse(job)
    overflow = [r for r in rows if r.status == "OVER"]
    tight = [r for r in rows if r.status == "TIGHT"]
    for r in overflow:
        print(f"OVER: {r.plane} flows {float(r.flow):.3f} L/s against {r.capacity:.3f} L/s capacity")
    for r in tight:
        print(f"TIGHT: {r.plane} runs at {r.use * 100:.1f}% of capacity")
    if overflow or (args.strict and tight):
        return 1
    print(f"check passed: {len(rows)} planes, none over capacity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
