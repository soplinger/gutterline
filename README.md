# Gutterline

**Size your gutters and downspouts from one plain-text file, offline.**

Gutterline reads a short job file describing your roof planes, rainfall and the parts you plan to buy. It works out the design flow for each plane, checks it against full-section gutter capacity, counts the downspouts and hangers you need, plans the stock cuts, and prices the job to the cent. It runs on the Python standard library, makes no network calls, and needs no account.

## Features

- **Drainage area and design flow per roof plane.** Uses the rational method, `Q = i × A / 3600` in L/s, with exact fractions.
- **Gutter capacity for round and box profiles.** Manning's equation for a full section, using your roughness value and fall.
- **Utilisation status per plane.** `OK` at or below your limit, `TIGHT` above the limit, `OVER` above full capacity.
- **Downspout outlets.** The count is the larger of the flow-based and spacing-based numbers, and the report shows the resulting spacing.
- **Hanger count per run.** Brackets every `hanger` metres, plus one at the end.
- **Stock cut plan.** Pieces of stock length per run, the joints they create, and the length bought.
- **Exact cost in cents.** Gutter stock plus downspouts, rounded half-up.
- **`pick`: smallest standard round gutter** (100, 125, 150 or 175 mm) that keeps every plane within your limit.
- **`lint`: line-numbered errors and warnings.** Catches unknown directives, bad numbers, duplicate settings and duplicate planes.
- **Fall warnings.** Flags a fall flatter than 1:500 (water may pond) or steeper than 1:50.
- **`check`: CI gate.** Exit `0` when everything fits, `1` when a plane overflows (or any plane is tight with `--strict`), and `2` for an invalid file.
- **`--rain` what-if override.** Re-run any command at a different design rainfall without editing the file.

## Quick start

Requires Python 3.9 or newer. There is nothing to install.

```bash
python3 gutterline.py report examples/house.gl
```

The sample job covers three roof planes (`front`, `rear`, `garage`) with a 125 mm round gutter at 1:200 fall and 100 mm/h design rain. The `front` plane runs at about 84% of gutter capacity, so the report marks it `TIGHT`. The job's total comes to **603.00**: gutter stock 555.00 plus downspouts 48.00.

Find the smallest standard round gutter that fits the same roof:

```bash
python3 gutterline.py pick examples/house.gl
# smallest standard round gutter: 150 mm
```

Check the job as a CI gate, and run a what-if at a much heavier storm:

```bash
python3 gutterline.py check examples/house.gl
python3 gutterline.py check examples/house.gl --rain 400   # exits 1: planes overflow
```

## Job file format

One directive per line. `#` starts a comment. Lines may appear in any order.

| Directive | Meaning |
| --- | --- |
| `rain MM_PER_H` | Design rainfall intensity (required) |
| `gutter round D_MM price=X` or `gutter box W_MM H_MM price=X` | Gutter profile and internal size, price per metre (required) |
| `downspout D_MM capacity=L_PER_S price=X` | Downspout size, capacity from your product data, price each (required) |
| `plane NAME LENGTH_M RUN_M` | Gutter run length and roof run on plan (one or more required) |
| `fall 1:N` | Gutter fall, default `1:200` |
| `roughness N` | Manning n, default `0.012` |
| `hanger M` | Bracket spacing, default `0.6` |
| `stock M` | Stock length bought, default `3.0` |
| `max-spacing M` | Longest run allowed per downspout, default `12` |
| `limit F` | Utilisation above this fraction is `TIGHT`, default `0.8` |

Each single-value directive may appear once. A repeat is an error that names the first line.

## Commands

```text
gutterline report FILE [--rain MM_PER_H]          full plane, outlet, stock and cost report
gutterline lint FILE                              line-numbered issues; exit 2 if any errors
gutterline pick FILE [--rain MM_PER_H]            smallest standard round gutter that fits
gutterline check FILE [--rain MM_PER_H] [--strict]   CI gate: 0 pass, 1 overflow, 2 invalid
```

## How the numbers are worked out

- **Flow:** `Q [L/s] = rain [mm/h] × area [m²] / 3600`.
- **Round gutter, full section:** area `π·D²/8`, wetted perimeter `π·D/2 + D`.
- **Box gutter, full section:** area `W·H`, wetted perimeter `W + 2H`.
- **Capacity:** `Q = A · R^(2/3) · √S / n`, with `R = A / P` and `S = 1 / N` from `fall 1:N`.
- **Outlets:** `max(1, ⌈Q / downspout capacity⌉, ⌈run length / max-spacing⌉)`.
- **Stock:** `⌈length / stock⌉` pieces, bought in full stock lengths.

Capacity is a full-section estimate, so it is a planning figure, not a substitute for a drainage design check. Downspout capacity is whatever you enter from the manufacturer's data.

## Running the tests

```bash
python3 -m pytest -q tests
```

The tests use `pytest` and cover parsing and line numbers, exact flow, hand-checked Manning capacities, outlet and stock rules, cost rounding, `pick`, the rain override, exit codes and the sample report. Nothing writes outside the temporary directories the tests create.

## Project layout

```text
gutterline.py              the planner and CLI (standard library only)
examples/house.gl          sample three-plane job
tests/conftest.py          puts the project root on the import path
tests/test_gutterline.py   unit and CLI tests
```

## Licence

No licence file is included yet. Add one before you publish.
