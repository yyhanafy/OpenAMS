#!/usr/bin/env python3

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate-json", required=True)
    ap.add_argument(
        "--workspace",
        default="~/AMS-Tutorial/laygo2_workspace_sky130",
    )
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    ws = Path(args.workspace).expanduser().resolve()
    candidate_path = Path(args.candidate_json).resolve()
    out = Path(args.output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    data = json.loads(candidate_path.read_text())

    sys.path.insert(0, str(ws / "laygo2"))
    sys.path.insert(0, str(ws))
    sys.path.insert(0, str(ws / "skywater130"))

    old_cwd = Path.cwd()
    os.chdir(ws / "skywater130")

    try:
        import laygo2
        import laygo2.interface
        import laygo2_tech as tech

        templates = tech.load_templates()
        grids = tech.load_grids(templates=templates)
    finally:
        os.chdir(old_cwd)

    pg = grids["placement_basic"]
    r12 = grids["routing_12_cmos"]
    r23 = grids["routing_23_cmos"]

    #
    # Generate candidate-specific native MOS devices.
    #
    inst = {}

    for name, spec in data["devices"].items():
        t = templates[spec["type"]]

        inst[name] = t.generate(
            name=name,
            params={
                "nf": int(spec["nf"]),
                "nfdmyl": 0,
                "nfdmyr": 0,
                "bndl": True,
                "bndr": True,
                "gbndl": False,
                "gbndr": False,
                "trackswap": False,
                "tie": None,
            },
        )

    m1 = inst["M1"]
    m2 = inst["M2"]
    m3 = inst["M3"]
    m4 = inst["M4"]
    m5 = inst["M5"]
    m6 = inst["M6"]
    m7 = inst["M7"]

    libname = "openams_fabo"
    cellname = data["physical_candidate_id"]

    lib = laygo2.object.database.Library(name=libname)
    dsn = laygo2.object.database.Design(
        name=cellname,
        libname=libname,
    )
    lib.append(dsn)

    #
    # Simple generic row placement.
    #
    # All MOS instances are 5 placement-grid rows high.
    #
    # PMOS row
    #   M3 ---- M4 ---------------- M6
    #
    # input row
    #   M1 ---- M2
    #
    # NMOS bias/output row
    #   M5 ------------------------ M7
    #
    gap_x = 8
    gap_y = 4

    h = 5

    # Bottom row.
    m5_xy = np.array([0, 0])
    m7_xy = np.array([
        pg.mn.width_vec(m5)[0] + gap_x,
        0,
    ])

    # Input row.
    #
    # Keep the input-pair source access off the routing_23_cmos
    # periodic boundary.  With input_y=9 placement rows, M1/M2.S
    # landed exactly at physical y=830, which selected the dummy
    # via_M2_M3_1 and produced an open connection.
    #
    # input_y=8 was validated by Magic extraction:
    #     M1.S = M2.S = M5.D = NTAIL
    #
    input_y = 8

    m1_xy = np.array([0, input_y])
    m2_xy = np.array([
        pg.mn.width_vec(m1)[0] + gap_x,
        input_y,
    ])

    # PMOS row.
    pmos_y = 2 * (h + gap_y)

    m3_xy = np.array([0, pmos_y])
    m4_xy = np.array([
        pg.mn.width_vec(m3)[0] + gap_x,
        pmos_y,
    ])

    m6_xy = np.array([
        pg.mn.width_vec(m3)[0]
        + gap_x
        + pg.mn.width_vec(m4)[0]
        + 2 * gap_x,
        pmos_y,
    ])

    #
    # Place.
    #
    for dev, mn in [
        (m5, m5_xy),
        (m7, m7_xy),
        (m1, m1_xy),
        (m2, m2_xy),
        (m3, m3_xy),
        (m4, m4_xy),
        (m6, m6_xy),
    ]:
        dsn.place(grid=pg, inst=dev, mn=mn)

    print("\n===== ABSOLUTE TERMINAL COORDINATES =====")

    for name in ["M1","M2","M3","M4","M5","M6","M7"]:
        dev = inst[name]

        print(name)
        for pin_name in ["G", "D", "S", "RAIL"]:
            b = r23.mn.bbox(dev.pins[pin_name])
            print(
                f"  {pin_name:<4} "
                f"{b.tolist()}"
            )

    #
    # Routing helpers.
    #
    # Do NOT simply use the geometric center for every terminal.
    #
    # On this technology the small-device D bbox can quantize across
    # two routing rows (for example M1.D gives y=9..10 while M1.G is
    # y=10).  To keep D and G electrically separate:
    #
    #   G -> upper routing coordinate
    #   D -> lower routing coordinate
    #   S -> center
    #   RAIL -> lower routing coordinate
    #
    def terminal_point(grid, dev, pin_name):
        b = grid.mn.bbox(dev.pins[pin_name])

        xmin = int(min(b[0][0], b[1][0]))
        xmax = int(max(b[0][0], b[1][0]))
        ymin = int(min(b[0][1], b[1][1]))
        ymax = int(max(b[0][1], b[1][1]))

        x = int(round((xmin + xmax) / 2))

        if pin_name == "G":
            y = ymax
        elif pin_name == "D":
            y = ymin
        elif pin_name == "RAIL":
            y = ymin
        else:
            y = int(round((ymin + ymax) / 2))

        return np.array([x, y], dtype=int)

    def routed_pin(name, grid, route, fallback_pin):
        #
        # Label a known physical terminal belonging to the routed net.
        # This is safer than trying to infer which object returned by
        # route_via_track is the desired external segment.
        #
        dsn.pin(
            name=name,
            grid=grid,
            mn=grid.mn.bbox(fallback_pin),
        )

    #
    # ============================================================
    # NTAIL
    #
    # M1.S = M2.S = M5.D
    #
    # VALIDATED routing:
    #   - use right-side terminal endpoints
    #   - escape horizontally outside all three devices
    #   - join vertically in a dedicated corridor
    #
    # This exact topology was verified by Magic extraction:
    #     M1.S = M2.S = M5.D = NTAIL
    # ============================================================
    #
    ntail_m5d = r23.mn(m5.pins["D"])[1]
    ntail_m1s = r23.mn(m1.pins["S"])[1]
    ntail_m2s = r23.mn(m2.pins["S"])[1]

    NTAIL_X = 50

    # M5.D -> external corridor.
    v5a, ntail_5, v5b = dsn.route(
        grid=r23,
        mn=[
            ntail_m5d,
            np.array([NTAIL_X, ntail_m5d[1]]),
        ],
        via_tag=[True, True],
    )

    # M1.S -> external corridor.
    v1a, ntail_1, v1b = dsn.route(
        grid=r23,
        mn=[
            ntail_m1s,
            np.array([NTAIL_X, ntail_m1s[1]]),
        ],
        via_tag=[True, True],
    )

    # M2.S -> external corridor.
    v2a, ntail_2, v2b = dsn.route(
        grid=r23,
        mn=[
            ntail_m2s,
            np.array([NTAIL_X, ntail_m2s[1]]),
        ],
        via_tag=[True, True],
    )

    # Join M5.D level to M1/M2 source level.
    ntail_vertical = dsn.route(
        grid=r23,
        mn=[
            np.array([NTAIL_X, ntail_m5d[1]]),
            np.array([NTAIL_X, ntail_m1s[1]]),
        ],
    )

    ntail_route = ntail_1

    #
    # ============================================================
    # N1
    #
    # M1.D = M3.D = M3.G = M4.G
    #
    # Use another left-side vertical corridor.
    # ============================================================
    #
    n1_pts = [
        terminal_point(r23, m1, "D"),
        terminal_point(r23, m3, "D"),
        terminal_point(r23, m3, "G"),
        terminal_point(r23, m4, "G"),
    ]

    N1_X = -8

    n1_route = dsn.route_via_track(
        grid=r23,
        mn=n1_pts,
        track=[N1_X, None],
    )

    #
    # ============================================================
    # N2
    #
    # M2.D = M4.D = M6.G
    #
    # M4 ends around x=108 and M6 starts around x=116.
    # Put the N2 vertical spine in that guaranteed empty corridor.
    # This avoids crossing M6.D, which belongs to OUT.
    # ============================================================
    #
    n2_pts = [
        terminal_point(r23, m2, "D"),
        terminal_point(r23, m4, "D"),
        terminal_point(r23, m6, "G"),
    ]

    N2_X = 112

    n2_route = dsn.route_via_track(
        grid=r23,
        mn=n2_pts,
        track=[N2_X, None],
    )

    #
    # ============================================================
    # OUT
    #
    # M6.D = M7.D
    #
    # Safe endpoint escape:
    # M7 is to the right of M5, therefore escape from the RIGHT
    # endpoint of M7.D.  Do not allow an OUT wire to run leftward
    # across the M5.D/NTAIL track.
    # ============================================================
    #
    out_m7d = r23.mn(m7.pins["D"])[1]
    out_m6d = r23.mn(m6.pins["D"])[1]

    OUT_X = 170

    # M7.D -> far-right OUT corridor.
    vo7a, out_7, vo7b = dsn.route(
        grid=r23,
        mn=[
            out_m7d,
            np.array([OUT_X, out_m7d[1]]),
        ],
        via_tag=[True, True],
    )

    # M6.D -> same corridor.
    vo6a, out_6, vo6b = dsn.route(
        grid=r23,
        mn=[
            out_m6d,
            np.array([OUT_X, out_m6d[1]]),
        ],
        via_tag=[True, True],
    )

    # Vertical OUT spine.
    out_vertical = dsn.route(
        grid=r23,
        mn=[
            np.array([OUT_X, out_m7d[1]]),
            np.array([OUT_X, out_m6d[1]]),
        ],
    )

    out_route = out_7

    #
    # ============================================================
    # VBIAS
    #
    # M5.G = M7.G
    #
    # Both gates are already on y=3.
    # Route DIRECTLY on the gate track.
    #
    # The old implementation used gate_y - 2 = 1, which is exactly
    # the M5/M7 SOURCE track and caused the extracted VBIAS/VSS
    # short.
    # ============================================================
    #
    vbias_pts = [
        terminal_point(r23, m5, "G"),
        terminal_point(r23, m7, "G"),
    ]

    VBIAS_Y = 3

    vbias_route = dsn.route_via_track(
        grid=r23,
        mn=vbias_pts,
        track=[None, VBIAS_Y],
    )

    #
    # ============================================================
    # VSS
    #
    # For native NMOS:
    #   source S + body/rail RAIL -> VSS
    #
    # M5 and M7 are on the same row.
    # Keep source connection on y=1 and rail on y=0.
    # ============================================================
    #
    vss_source_pts = [
        terminal_point(r12, m5, "S"),
        terminal_point(r12, m7, "S"),
    ]

    vss_source_route = dsn.route_via_track(
        grid=r12,
        mn=vss_source_pts,
        track=[None, 1],
    )

    vss_rail_pts = [
        terminal_point(r12, m5, "RAIL"),
        terminal_point(r12, m7, "RAIL"),
    ]

    vss_rail_route = dsn.route_via_track(
        grid=r12,
        mn=vss_rail_pts,
        track=[None, 0],
    )

    #
    # Join the VSS source and rail networks in a safe far-right
    # corridor, outside M7.
    #
    VSS_JOIN_X = 50

    dsn.route_via_track(
        grid=r12,
        mn=[
            np.array([VSS_JOIN_X, 0]),
            np.array([VSS_JOIN_X, 1]),
        ],
        track=[VSS_JOIN_X, None],
    )

    #
    # ============================================================
    # VDD
    #
    # For native PMOS:
    #   source S + body/rail RAIL -> VDD
    #
    # PMOS source is y=15.  RAIL spans y=14..15.
    # ============================================================
    #
    vdd_source_pts = [
        terminal_point(r12, m3, "S"),
        terminal_point(r12, m4, "S"),
        terminal_point(r12, m6, "S"),
    ]

    vdd_source_route = dsn.route_via_track(
        grid=r12,
        mn=vdd_source_pts,
        track=[None, 15],
    )

    vdd_rail_pts = [
        terminal_point(r12, m3, "RAIL"),
        terminal_point(r12, m4, "RAIL"),
        terminal_point(r12, m6, "RAIL"),
    ]

    vdd_rail_route = dsn.route_via_track(
        grid=r12,
        mn=vdd_rail_pts,
        track=[None, 14],
    )

    #
    # Join source and body/rail at far right of PMOS row.
    #
    VDD_JOIN_X = 170

    dsn.route_via_track(
        grid=r12,
        mn=[
            np.array([VDD_JOIN_X, 14]),
            np.array([VDD_JOIN_X, 15]),
        ],
        track=[VDD_JOIN_X, None],
    )

    #
    # ============================================================
    # Top-level pins.
    # ============================================================
    #
    dsn.pin(
        name="INP",
        grid=r23,
        mn=r23.mn.bbox(m1.pins["G"]),
    )

    dsn.pin(
        name="INN",
        grid=r23,
        mn=r23.mn.bbox(m2.pins["G"]),
    )

    routed_pin(
        "OUT",
        r23,
        out_route,
        m7.pins["D"],
    )

    routed_pin(
        "VBIAS",
        r23,
        vbias_route,
        m5.pins["G"],
    )

    routed_pin(
        "VSS",
        r12,
        vss_rail_route,
        m5.pins["RAIL"],
    )

    routed_pin(
        "VDD",
        r12,
        vdd_rail_route,
        m3.pins["RAIL"],
    )

    #
    # Export template/GDS/Magic TCL.
    #
    tcl = out / "export.tcl"
    gds = out / f"{cellname}.gds"

    os.chdir(ws)

    laygo2.interface.magic.export(
        lib,
        filename=str(tcl),
        cellname=None,
        libpath=str(ws / "magic_layout"),
        scale=0.5,
        reset_library=False,
        tech_library="sky130A",
        gds_filename=str(gds),
    )

    #
    # Add primitive search path and quit.
    #
    micro = (
        ws
        / "magic_layout"
        / "skywater130_microtemplates_dense"
    )

    text = tcl.read_text()

    tcl.write_text(
        f"path search +{micro}\n"
        + text
        + "\nquit -noprompt\n"
    )

    print("===== NATIVE TWO-STAGE LAYOUT BUILT =====")
    print("candidate :", cellname)

    for name in ["M1","M2","M3","M4","M5","M6","M7"]:
        i = inst[name]
        print(
            f"{name}: "
            f"xy={i.xy.tolist()} "
            f"bbox={i.bbox.tolist()}"
        )

    print()
    print("export TCL :", tcl)
    print("GDS        :", gds)


if __name__ == "__main__":
    main()
