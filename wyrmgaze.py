#!/usr/bin/env python3
"""
wyrmgaze.py - Pentest action graph generator

Action file format — wrap the action in *asterisks*, everything before is
input, everything after is result. Multiple inputs/results supported:

    port 80 | *login* | guest
    guest | *found* | file1 | username
    file1 | *read* | password
    password | username | *ssh login* | root

Usage:
    python wyrmgaze.py actions.txt               # horizontal (default)
    python wyrmgaze.py actions.txt --vertical    # vertical layout
    python wyrmgaze.py actions.txt --hybrid      # hybrid layout
    python wyrmgaze.py actions.txt --markdown    # also save a .md table
    python wyrmgaze.py actions.txt -o out.svg
    cat actions.txt | python wyrmgaze.py -
"""

import sys
import argparse
from pathlib import Path

PALETTES = [
    ("#378ADD", "#85B7EB", "#E6F1FB"),
    ("#1D9E75", "#5DCAA5", "#E1F5EE"),
    ("#D85A30", "#F0997B", "#FAECE7"),
    ("#D4537E", "#ED93B1", "#FBEAF0"),
    ("#BA7517", "#EF9F27", "#FAEEDA"),
    ("#639922", "#97C459", "#EAF3DE"),
    ("#E24B4A", "#F09595", "#FCEBEB"),
    ("#888780", "#B4B2A9", "#F1EFE8"),
]

ACT_FILL    = "#7F77DD"
ACT_STROKE  = "#AFA9EC"
ACT_TEXT    = "#EEEDFE"
CONN_COLOR  = "#555553"
BG_COLOR    = "#0a0a0a"
FONT        = "Arial, sans-serif"

# shared sizing
DATA_H      = 30
CHAR_W_BOX  = 7.5
CHAR_W_ACT  = 7.2
BOX_PAD_X   = 16
ACT_RY      = 16
ACT_RX_PAD  = 14
ACT_RX_MIN  = 30

# horizontal layout
H_COL_GAP   = 60
H_PAD_X     = 40
H_PAD_Y_TOP = 40
H_PAD_Y_BOT = 40
H_LANE_H    = 18
H_ARROW_V   = 22
H_NODE_GAP  = 8

# vertical layout
V_ROW_GAP   = 50
V_PAD_X     = 60
V_PAD_Y     = 40
V_ARROW_H   = 30
V_NODE_GAP  = 8
V_LANE_W    = 18

# hybrid layout
MAX_SVG_W   = 1400
H_STRIP_GAP = 80


# ── shared helpers ───────────────────────────────────────────────────────────

def text_width(label, char_w):
    return len(label) * char_w

def box_width(label):
    return max(80, int(text_width(label, CHAR_W_BOX) + BOX_PAD_X * 2))

def action_rx(label):
    return max(ACT_RX_MIN, int(text_width(label, CHAR_W_ACT) / 2 + ACT_RX_PAD))

def safe_marker_id(val):
    return "ar_" + "".join(c if c.isalnum() else "_" for c in val)

def arrow_marker(mid, stroke):
    return (f'<marker id="{mid}" viewBox="0 0 10 10" refX="8" refY="5" '
            f'markerWidth="5" markerHeight="5" orient="auto-start-reverse">'
            f'<path d="M2 1L8 5L2 9" fill="none" stroke="{stroke}" '
            f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
            f'</marker>')

def data_box(cx, y, label, fill, stroke, text_color):
    w  = box_width(label)
    bx = cx - w / 2
    return (f'<rect x="{bx:.1f}" y="{y:.1f}" width="{w}" height="{DATA_H}" rx="6" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="0.5"/>\n'
            f'<text x="{cx:.1f}" y="{y + DATA_H/2:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-family="{FONT}" '
            f'font-size="12" font-weight="500" fill="{text_color}">'
            f'{label}</text>')

def draw_action_ellipse(cx, cy, label):
    rx = action_rx(label)
    return (f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx}" ry="{ACT_RY}" '
            f'fill="{ACT_FILL}" stroke="{ACT_STROKE}" stroke-width="0.5"/>\n'
            f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-family="{FONT}" '
            f'font-size="11" font-weight="500" fill="{ACT_TEXT}">'
            f'{label}</text>')


# ── parsing ──────────────────────────────────────────────────────────────────

def parse_actions(lines):
    actions = []
    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]
        action_label = action_idx = None
        for j, p in enumerate(parts):
            if p.startswith("*") and p.endswith("*") and len(p) > 2:
                if action_label is None:
                    action_label = p[1:-1].strip()
                    action_idx   = j
        if action_label is None:
            print(f"Warning: no *action* on line {i} — skipping", file=sys.stderr)
            continue
        inputs  = [p for j, p in enumerate(parts) if j < action_idx]
        results = [p for j, p in enumerate(parts) if j > action_idx]
        if not inputs or not results:
            print(f"Warning: line {i} needs at least one input and one result — skipping", file=sys.stderr)
            continue
        actions.append({"inputs": inputs, "action": action_label, "results": results})
    return actions

def assign_colors(actions):
    color_map = {}
    idx = 0
    for a in actions:
        for val in a["inputs"] + a["results"]:
            if val not in color_map:
                color_map[val] = PALETTES[idx % len(PALETTES)]
                idx += 1
    return color_map

def find_all_shared(actions):
    val_cols = {}
    for i, a in enumerate(actions):
        for v in a["results"]:
            val_cols.setdefault(v, []).append((i, "result"))
        for v in a["inputs"]:
            val_cols.setdefault(v, []).append((i, "input"))
    adjacent, non_adjacent = [], []
    seen = set()
    for val, positions in val_cols.items():
        result_rows = sorted(set(c for c, r in positions if r == "result"))
        input_rows  = sorted(set(c for c, r in positions if r == "input"))
        for rc in result_rows:
            for ic in input_rows:
                if ic <= rc:
                    continue
                key = (val, rc, ic)
                if key in seen:
                    continue
                seen.add(key)
                if ic == rc + 1:
                    adjacent.append(key)
                else:
                    non_adjacent.append(key)
    return adjacent, non_adjacent


# ── HORIZONTAL layout ────────────────────────────────────────────────────────

def h_col_width(a):
    rx  = action_rx(a["action"])
    bws = [box_width(v) for v in a["inputs"] + a["results"]]
    return max(rx * 2, max(bws))

def h_col_layout(a, graph_top):
    n_in        = len(a["inputs"])
    inputs_h    = n_in * DATA_H + (n_in - 1) * H_NODE_GAP
    y_act_mid   = graph_top + inputs_h + H_ARROW_V + ACT_RY
    y_res_start = y_act_mid + ACT_RY + H_ARROW_V
    return inputs_h, y_act_mid, y_res_start

def generate_horizontal(actions, color_map):
    n = len(actions)
    adjacent, non_adjacent = find_all_shared(actions)

    lane_slots = {}
    slot_ends  = []
    for link in non_adjacent:
        val, rc, ic = link
        assigned = None
        for s, end in enumerate(slot_ends):
            if end < rc:
                assigned = s; slot_ends[s] = ic; break
        if assigned is None:
            assigned = len(slot_ends); slot_ends.append(ic)
        lane_slots[link] = assigned

    num_lanes = len(slot_ends)
    graph_top = H_PAD_Y_TOP + num_lanes * H_LANE_H

    col_widths = [h_col_width(a) for a in actions]
    col_cx = []
    x = H_PAD_X
    for cw in col_widths:
        col_cx.append(x + cw / 2)
        x += cw + H_COL_GAP

    max_bottom = 0
    for a in actions:
        _, _, y_res_start = h_col_layout(a, graph_top)
        n_res  = len(a["results"])
        bottom = y_res_start + n_res * DATA_H + (n_res - 1) * H_NODE_GAP
        max_bottom = max(max_bottom, bottom)

    svg_w = max(680, int(x - H_COL_GAP + H_PAD_X))
    svg_h = max_bottom + H_PAD_Y_BOT

    defs = ["<defs>", arrow_marker("ar", CONN_COLOR)]
    seen_m = set()
    for val, rc, ic in adjacent + non_adjacent:
        mid = safe_marker_id(val)
        if mid not in seen_m:
            defs.append(arrow_marker(mid, color_map[val][1])); seen_m.add(mid)
    defs.append("</defs>")
    parts = defs[:]

    for val, rc, ic in adjacent:
        color = color_map[val]; mid = safe_marker_id(val)
        _, _, y_res_start_rc = h_col_layout(actions[rc], graph_top)
        y_from = y_res_start_rc + actions[rc]["results"].index(val) * (DATA_H + H_NODE_GAP) + DATA_H / 2
        y_to   = graph_top + actions[ic]["inputs"].index(val) * (DATA_H + H_NODE_GAP) + DATA_H / 2
        x1 = col_cx[rc] + box_width(val) / 2
        x2 = col_cx[ic] - box_width(val) / 2 - 4
        parts.append(f'<line x1="{x1:.1f}" y1="{y_from:.1f}" x2="{x2:.1f}" y2="{y_to:.1f}" '
                     f'stroke="{color[1]}" stroke-width="1.5" stroke-dasharray="5 3" '
                     f'marker-end="url(#{mid})"/>')

    for val, rc, ic in non_adjacent:
        color = color_map[val]; mid = safe_marker_id(val)
        slot  = lane_slots[(val, rc, ic)]
        lane_y = graph_top - (slot + 1) * H_LANE_H + H_LANE_H // 2
        _, _, y_res_start_rc = h_col_layout(actions[rc], graph_top)
        y_src_top = y_res_start_rc + actions[rc]["results"].index(val) * (DATA_H + H_NODE_GAP)
        inp_idx   = actions[ic]["inputs"].index(val)
        y_dst_mid = graph_top + inp_idx * (DATA_H + H_NODE_GAP) + DATA_H / 2
        fx = col_cx[rc]; tx = col_cx[ic]
        parts.append(f'<path d="M{fx:.1f},{y_src_top:.1f} L{fx:.1f},{lane_y:.1f} '
                     f'L{tx:.1f},{lane_y:.1f} L{tx:.1f},{y_dst_mid:.1f}" '
                     f'fill="none" stroke="{color[1]}" stroke-width="1.2" '
                     f'stroke-dasharray="6 3" marker-end="url(#{mid})"/>')
        parts.append(f'<text x="{(fx+tx)/2:.1f}" y="{lane_y-4:.1f}" text-anchor="middle" '
                     f'font-family="{FONT}" font-size="10" fill="{color[1]}">{val}</text>')

    for i, a in enumerate(actions):
        x = col_cx[i]
        inputs_h, y_act_mid, y_res_start = h_col_layout(a, graph_top)
        parts.append(f'<line x1="{x:.1f}" y1="{graph_top+inputs_h:.1f}" '
                     f'x2="{x:.1f}" y2="{y_act_mid-ACT_RY-2:.1f}" '
                     f'stroke="{CONN_COLOR}" stroke-width="1" marker-end="url(#ar)"/>')
        parts.append(f'<line x1="{x:.1f}" y1="{y_act_mid+ACT_RY:.1f}" '
                     f'x2="{x:.1f}" y2="{y_res_start-2:.1f}" '
                     f'stroke="{CONN_COLOR}" stroke-width="1" marker-end="url(#ar)"/>')
        for j, val in enumerate(a["inputs"]):
            y = graph_top + j * (DATA_H + H_NODE_GAP)
            parts.append(data_box(x, y, val, *color_map[val]))
            if j < len(a["inputs"]) - 1:
                parts.append(f'<line x1="{x:.1f}" y1="{y+DATA_H:.1f}" x2="{x:.1f}" '
                             f'y2="{y+DATA_H+H_NODE_GAP:.1f}" stroke="{CONN_COLOR}" stroke-width="0.5"/>')
        parts.append(draw_action_ellipse(x, y_act_mid, a["action"]))
        for j, val in enumerate(a["results"]):
            y = y_res_start + j * (DATA_H + H_NODE_GAP)
            parts.append(data_box(x, y, val, *color_map[val]))
            if j < len(a["results"]) - 1:
                parts.append(f'<line x1="{x:.1f}" y1="{y+DATA_H:.1f}" x2="{x:.1f}" '
                             f'y2="{y+DATA_H+H_NODE_GAP:.1f}" stroke="{CONN_COLOR}" stroke-width="0.5"/>')

    return svg_w, svg_h, parts


# ── VERTICAL layout ──────────────────────────────────────────────────────────

def v_row_height(a):
    n_in  = len(a["inputs"])
    n_res = len(a["results"])
    h_in  = n_in  * DATA_H + (n_in  - 1) * V_NODE_GAP
    h_res = n_res * DATA_H + (n_res - 1) * V_NODE_GAP
    return max(h_in, h_res, ACT_RY * 2)

def v_row_layout(a, y_top):
    row_h   = v_row_height(a)
    cy      = y_top + row_h / 2
    n_in    = len(a["inputs"])
    h_in    = n_in * DATA_H + (n_in - 1) * V_NODE_GAP
    in_y0   = cy - h_in / 2
    n_res   = len(a["results"])
    h_res   = n_res * DATA_H + (n_res - 1) * V_NODE_GAP
    res_y0  = cy - h_res / 2
    return row_h, cy, in_y0, res_y0

def generate_vertical(actions, color_map):
    n = len(actions)
    adjacent, non_adjacent = find_all_shared(actions)

    lane_slots = {}
    slot_ends  = []
    for link in non_adjacent:
        val, rc, ic = link
        assigned = None
        for s, end in enumerate(slot_ends):
            if end < rc:
                assigned = s; slot_ends[s] = ic; break
        if assigned is None:
            assigned = len(slot_ends); slot_ends.append(ic)
        lane_slots[link] = assigned

    num_lanes   = len(slot_ends)
    max_in_box  = max(box_width(v) for a in actions for v in a["inputs"])
    max_res_box = max(box_width(v) for a in actions for v in a["results"])
    max_act_rx  = max(action_rx(a["action"]) for a in actions)

    lane_area   = V_PAD_X + num_lanes * V_LANE_W
    in_cx       = lane_area + max_in_box / 2
    ellipse_cx  = in_cx + max_in_box / 2 + V_ARROW_H + max_act_rx
    res_cx      = ellipse_cx + max_act_rx + V_ARROW_H + max_res_box / 2

    svg_w = max(680, int(res_cx + max_res_box / 2 + V_PAD_X))

    row_tops = []
    y = V_PAD_Y
    for a in actions:
        row_tops.append(y)
        y += v_row_height(a) + V_ROW_GAP

    svg_h = y - V_ROW_GAP + V_PAD_Y

    defs = ["<defs>", arrow_marker("ar", CONN_COLOR)]
    seen_m = set()
    for val, rc, ic in adjacent + non_adjacent:
        mid = safe_marker_id(val)
        if mid not in seen_m:
            defs.append(arrow_marker(mid, color_map[val][1])); seen_m.add(mid)
    defs.append("</defs>")
    parts = defs[:]

    for val, rc, ic in adjacent:
        color = color_map[val]; mid = safe_marker_id(val)
        _, _, _, res_y0_rc = v_row_layout(actions[rc], row_tops[rc])
        res_idx  = actions[rc]["results"].index(val)
        y_from   = res_y0_rc + res_idx * (DATA_H + V_NODE_GAP) + DATA_H / 2
        x_from   = res_cx + box_width(val) / 2
        _, _, in_y0_ic, _ = v_row_layout(actions[ic], row_tops[ic])
        inp_idx  = actions[ic]["inputs"].index(val)
        y_to     = in_y0_ic + inp_idx * (DATA_H + V_NODE_GAP) + DATA_H / 2
        x_to     = in_cx - box_width(val) / 2 - 4
        parts.append(
            f'<path d="M{x_from:.1f},{y_from:.1f} '
            f'C{x_from+40:.1f},{y_from:.1f} {x_from+40:.1f},{y_to:.1f} '
            f'{x_to:.1f},{y_to:.1f}" '
            f'fill="none" stroke="{color[1]}" stroke-width="1.5" stroke-dasharray="5 3" '
            f'marker-end="url(#{mid})"/>'
        )

    for val, rc, ic in non_adjacent:
        color  = color_map[val]; mid = safe_marker_id(val)
        slot   = lane_slots[(val, rc, ic)]
        lane_x = V_PAD_X + slot * V_LANE_W + V_LANE_W // 2
        _, _, _, res_y0_rc = v_row_layout(actions[rc], row_tops[rc])
        res_idx  = actions[rc]["results"].index(val)
        y_src    = res_y0_rc + res_idx * (DATA_H + V_NODE_GAP) + DATA_H / 2
        x_src    = in_cx - max_in_box / 2
        _, _, in_y0_ic, _ = v_row_layout(actions[ic], row_tops[ic])
        inp_idx  = actions[ic]["inputs"].index(val)
        y_dst    = in_y0_ic + inp_idx * (DATA_H + V_NODE_GAP) + DATA_H / 2
        x_dst    = in_cx - box_width(val) / 2
        parts.append(
            f'<path d="M{x_src:.1f},{y_src:.1f} '
            f'L{lane_x:.1f},{y_src:.1f} '
            f'L{lane_x:.1f},{y_dst:.1f} '
            f'L{x_dst:.1f},{y_dst:.1f}" '
            f'fill="none" stroke="{color[1]}" stroke-width="1.2" stroke-dasharray="6 3" '
            f'marker-end="url(#{mid})"/>'
        )
        mid_y = (y_src + y_dst) / 2
        parts.append(
            f'<text x="{lane_x - 3:.1f}" y="{mid_y:.1f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="10" fill="{color[1]}">{val}</text>'
        )

    for i, a in enumerate(actions):
        row_h, cy, in_y0, res_y0 = v_row_layout(a, row_tops[i])
        x_arr_from  = in_cx + max_in_box / 2
        x_arr_to    = ellipse_cx - action_rx(a["action"]) - 2
        x_arr_from2 = ellipse_cx + action_rx(a["action"])
        x_arr_to2   = res_cx - max_res_box / 2 - 2
        parts.append(f'<line x1="{x_arr_from:.1f}" y1="{cy:.1f}" '
                     f'x2="{x_arr_to:.1f}" y2="{cy:.1f}" '
                     f'stroke="{CONN_COLOR}" stroke-width="1" marker-end="url(#ar)"/>')
        parts.append(f'<line x1="{x_arr_from2:.1f}" y1="{cy:.1f}" '
                     f'x2="{x_arr_to2:.1f}" y2="{cy:.1f}" '
                     f'stroke="{CONN_COLOR}" stroke-width="1" marker-end="url(#ar)"/>')
        for j, val in enumerate(a["inputs"]):
            y = in_y0 + j * (DATA_H + V_NODE_GAP)
            parts.append(data_box(in_cx, y, val, *color_map[val]))
            if j < len(a["inputs"]) - 1:
                parts.append(f'<line x1="{in_cx:.1f}" y1="{y+DATA_H:.1f}" '
                             f'x2="{in_cx:.1f}" y2="{y+DATA_H+V_NODE_GAP:.1f}" '
                             f'stroke="{CONN_COLOR}" stroke-width="0.5"/>')
        parts.append(draw_action_ellipse(ellipse_cx, cy, a["action"]))
        for j, val in enumerate(a["results"]):
            y = res_y0 + j * (DATA_H + V_NODE_GAP)
            parts.append(data_box(res_cx, y, val, *color_map[val]))
            if j < len(a["results"]) - 1:
                parts.append(f'<line x1="{res_cx:.1f}" y1="{y+DATA_H:.1f}" '
                             f'x2="{res_cx:.1f}" y2="{y+DATA_H+V_NODE_GAP:.1f}" '
                             f'stroke="{CONN_COLOR}" stroke-width="0.5"/>')
        if i < n - 1:
            sep_y = row_tops[i] + row_h + V_ROW_GAP / 2
            parts.append(f'<line x1="{V_PAD_X:.1f}" y1="{sep_y:.1f}" '
                         f'x2="{svg_w - V_PAD_X:.1f}" y2="{sep_y:.1f}" '
                         f'stroke="{CONN_COLOR}" stroke-width="0.3" stroke-dasharray="2 6"/>')

    return svg_w, svg_h, parts


# ── HYBRID layout ────────────────────────────────────────────────────────────

def generate_hybrid(actions, color_map):
    n = len(actions)

    def strip_width(idxs):
        total = H_PAD_X * 2
        for i in idxs:
            total += h_col_width(actions[i]) + H_COL_GAP
        return total - H_COL_GAP

    strips = []
    current = []
    for i in range(n):
        candidate = current + [i]
        if current and strip_width(candidate) > MAX_SVG_W:
            strips.append(current)
            current = [i]
        else:
            current = candidate
    if current:
        strips.append(current)

    strip_col_cx    = []
    strip_graph_top = []
    strip_heights   = []

    y_cursor = H_PAD_Y_TOP
    for s, idxs in enumerate(strips):
        col_cx_s = []
        x = H_PAD_X
        for i in idxs:
            cw = h_col_width(actions[i])
            col_cx_s.append(x + cw / 2)
            x += cw + H_COL_GAP
        graph_top_s = y_cursor
        max_bottom  = 0
        for gi in idxs:
            _, _, y_res_start = h_col_layout(actions[gi], graph_top_s)
            n_res  = len(actions[gi]["results"])
            bottom = y_res_start + n_res * DATA_H + (n_res - 1) * H_NODE_GAP
            max_bottom = max(max_bottom, bottom)
        strip_col_cx.append(col_cx_s)
        strip_graph_top.append(graph_top_s)
        strip_heights.append(max_bottom - graph_top_s)
        y_cursor = max_bottom + H_STRIP_GAP

    svg_h_base = y_cursor - H_STRIP_GAP + H_PAD_Y_BOT

    adjacent, non_adjacent = find_all_shared(actions)

    def find_strip(gi):
        for s, idxs in enumerate(strips):
            if gi in idxs:
                return s, idxs.index(gi)
        return None, None

    within_adj, cross_strip_adj, non_adj_links = [], [], []
    for val, rc, ic in adjacent:
        s_rc, _ = find_strip(rc)
        s_ic, _ = find_strip(ic)
        if s_rc == s_ic:
            within_adj.append((val, rc, ic))
        else:
            cross_strip_adj.append((val, rc, ic, s_rc, s_ic))
    for val, rc, ic in non_adjacent:
        non_adj_links.append((val, rc, ic))

    lane_slots = {}
    slot_ends  = []
    for link in non_adj_links:
        val, rc, ic = link
        assigned = None
        for s, end in enumerate(slot_ends):
            if end < rc:
                assigned = s; slot_ends[s] = ic; break
        if assigned is None:
            assigned = len(slot_ends); slot_ends.append(ic)
        lane_slots[link] = assigned

    num_lanes   = len(slot_ends)
    lane_offset = num_lanes * H_LANE_H + H_PAD_X
    strip_col_cx = [[cx + lane_offset for cx in row] for row in strip_col_cx]

    svg_w = max(680, MAX_SVG_W + lane_offset)
    svg_h = svg_h_base

    defs = ["<defs>", arrow_marker("ar", CONN_COLOR)]
    seen_m = set()
    all_links = ([(v, rc, ic) for v, rc, ic in within_adj] +
                 [(v, rc, ic) for v, rc, ic, _, _ in cross_strip_adj] +
                 [(v, rc, ic) for v, rc, ic in non_adj_links])
    for val, rc, ic in all_links:
        mid = safe_marker_id(val)
        if mid not in seen_m:
            defs.append(arrow_marker(mid, color_map[val][1])); seen_m.add(mid)
    defs.append("</defs>")
    parts = defs[:]

    for val, rc, ic in within_adj:
        color = color_map[val]; mid = safe_marker_id(val)
        s_rc, local_rc = find_strip(rc)
        s_ic, local_ic = find_strip(ic)
        gt = strip_graph_top[s_rc]
        _, _, y_res_start_rc = h_col_layout(actions[rc], gt)
        y_from = y_res_start_rc + actions[rc]["results"].index(val) * (DATA_H + H_NODE_GAP) + DATA_H / 2
        y_to   = gt + actions[ic]["inputs"].index(val) * (DATA_H + H_NODE_GAP) + DATA_H / 2
        x1 = strip_col_cx[s_rc][local_rc] + box_width(val) / 2
        x2 = strip_col_cx[s_ic][local_ic] - box_width(val) / 2 - 4
        parts.append(f'<line x1="{x1:.1f}" y1="{y_from:.1f}" x2="{x2:.1f}" y2="{y_to:.1f}" '
                     f'stroke="{color[1]}" stroke-width="1.5" stroke-dasharray="5 3" '
                     f'marker-end="url(#{mid})"/>')

    for val, rc, ic, s_rc, s_ic in cross_strip_adj:
        color = color_map[val]; mid = safe_marker_id(val)
        local_rc = strips[s_rc].index(rc)
        local_ic = strips[s_ic].index(ic)
        gt_rc = strip_graph_top[s_rc]
        _, _, y_res_start_rc = h_col_layout(actions[rc], gt_rc)
        y_from = y_res_start_rc + actions[rc]["results"].index(val) * (DATA_H + H_NODE_GAP) + DATA_H / 2
        fx = strip_col_cx[s_rc][local_rc]
        gt_ic = strip_graph_top[s_ic]
        y_to  = gt_ic + actions[ic]["inputs"].index(val) * (DATA_H + H_NODE_GAP) + DATA_H / 2
        tx = strip_col_cx[s_ic][local_ic]
        gap_y = gt_ic - H_STRIP_GAP / 2
        parts.append(
            f'<path d="M{fx:.1f},{y_from:.1f} L{fx:.1f},{gap_y:.1f} '
            f'L{tx:.1f},{gap_y:.1f} L{tx:.1f},{y_to:.1f}" '
            f'fill="none" stroke="{color[1]}" stroke-width="1.5" stroke-dasharray="5 3" '
            f'marker-end="url(#{mid})"/>'
        )
        parts.append(f'<text x="{(fx+tx)/2:.1f}" y="{gap_y - 4:.1f}" text-anchor="middle" '
                     f'font-family="{FONT}" font-size="10" fill="{color[1]}">{val}</text>')

    for val, rc, ic in non_adj_links:
        color  = color_map[val]; mid = safe_marker_id(val)
        slot   = lane_slots[(val, rc, ic)]
        s_rc, local_rc = find_strip(rc)
        s_ic, local_ic = find_strip(ic)
        gt_rc = strip_graph_top[s_rc]
        _, _, y_res_start_rc = h_col_layout(actions[rc], gt_rc)
        res_idx   = actions[rc]["results"].index(val)
        y_src_top = y_res_start_rc + res_idx * (DATA_H + H_NODE_GAP)
        fx = strip_col_cx[s_rc][local_rc]
        gt_ic = strip_graph_top[s_ic]
        inp_idx   = actions[ic]["inputs"].index(val)
        y_dst_mid = gt_ic + inp_idx * (DATA_H + H_NODE_GAP) + DATA_H / 2
        tx = strip_col_cx[s_ic][local_ic]
        x_left = lane_offset - (slot + 1) * H_LANE_H + H_LANE_H // 2
        parts.append(
            f'<path d="M{fx:.1f},{y_src_top:.1f} L{x_left:.1f},{y_src_top:.1f} '
            f'L{x_left:.1f},{y_dst_mid:.1f} L{tx - box_width(val)/2:.1f},{y_dst_mid:.1f}" '
            f'fill="none" stroke="{color[1]}" stroke-width="1.2" stroke-dasharray="6 3" '
            f'marker-end="url(#{mid})"/>'
        )
        mid_y = (y_src_top + y_dst_mid) / 2
        parts.append(f'<text x="{x_left - 3:.1f}" y="{mid_y:.1f}" text-anchor="end" '
                     f'font-family="{FONT}" font-size="10" fill="{color[1]}">{val}</text>')

    for s, idxs in enumerate(strips):
        gt = strip_graph_top[s]
        parts.append(f'<rect x="0" y="{gt - 10:.1f}" width="{svg_w}" '
                     f'height="{strip_heights[s] + 20:.1f}" rx="0" '
                     f'fill="#111111" opacity="0.5"/>')
        for local_i, gi in enumerate(idxs):
            a = actions[gi]
            x = strip_col_cx[s][local_i]
            inputs_h, y_act_mid, y_res_start = h_col_layout(a, gt)
            parts.append(f'<line x1="{x:.1f}" y1="{gt+inputs_h:.1f}" '
                         f'x2="{x:.1f}" y2="{y_act_mid-ACT_RY-2:.1f}" '
                         f'stroke="{CONN_COLOR}" stroke-width="1" marker-end="url(#ar)"/>')
            parts.append(f'<line x1="{x:.1f}" y1="{y_act_mid+ACT_RY:.1f}" '
                         f'x2="{x:.1f}" y2="{y_res_start-2:.1f}" '
                         f'stroke="{CONN_COLOR}" stroke-width="1" marker-end="url(#ar)"/>')
            for j, val in enumerate(a["inputs"]):
                y = gt + j * (DATA_H + H_NODE_GAP)
                parts.append(data_box(x, y, val, *color_map[val]))
                if j < len(a["inputs"]) - 1:
                    parts.append(f'<line x1="{x:.1f}" y1="{y+DATA_H:.1f}" '
                                 f'x2="{x:.1f}" y2="{y+DATA_H+H_NODE_GAP:.1f}" '
                                 f'stroke="{CONN_COLOR}" stroke-width="0.5"/>')
            parts.append(draw_action_ellipse(x, y_act_mid, a["action"]))
            for j, val in enumerate(a["results"]):
                y = y_res_start + j * (DATA_H + H_NODE_GAP)
                parts.append(data_box(x, y, val, *color_map[val]))
                if j < len(a["results"]) - 1:
                    parts.append(f'<line x1="{x:.1f}" y1="{y+DATA_H:.1f}" '
                                 f'x2="{x:.1f}" y2="{y+DATA_H+H_NODE_GAP:.1f}" '
                                 f'stroke="{CONN_COLOR}" stroke-width="0.5"/>')

    return svg_w, svg_h, parts


# ── SVG wrapper ───────────────────────────────────────────────────────────────

def wrap_svg(svg_w, svg_h, parts):
    return (f'<svg width="{svg_w}" height="{svg_h}" viewBox="0 0 {svg_w} {svg_h}" '
            f'xmlns="http://www.w3.org/2000/svg" style="background:{BG_COLOR}">\n'
            f'<rect width="{svg_w}" height="{svg_h}" fill="{BG_COLOR}"/>\n'
            + "\n".join(parts) + "\n</svg>")


# ── markdown table ────────────────────────────────────────────────────────────

def generate_markdown(actions, layouts_files):
    """
    layouts_files: list of (layout_name, svg_filename) tuples
    Generates a single .md with all orientations and the actions table.
    """
    w_inputs = max(len("inputs"),  max(len(", ".join(a["inputs"]))  for a in actions))
    w_action = max(len("action"),  max(len(a["action"])              for a in actions))
    w_results= max(len("results"), max(len(", ".join(a["results"])) for a in actions))

    header = f"| # | {'inputs'.ljust(w_inputs)} | {'action'.ljust(w_action)} | {'results'.ljust(w_results)} |"
    sep    = f"|---|{'-'*(w_inputs+2)}|{'-'*(w_action+2)}|{'-'*(w_results+2)}|"
    rows   = []
    for i, a in enumerate(actions, 1):
        rows.append(f"| {i} | {', '.join(a['inputs']).ljust(w_inputs)} | {a['action'].ljust(w_action)} | {', '.join(a['results']).ljust(w_results)} |")

    graph_sections = []
    for layout, svg_filename in layouts_files:
        graph_sections.append(f"### {layout.capitalize()}\n\n![]({svg_filename})")

    return "\n".join([
        "# Pentest Graph",
        "",
        f"**Actions:** {len(actions)}",
        "",
        "## Graphs",
        "",
        "\n\n".join(graph_sections),
        "",
        "## Actions",
        "",
        header, sep,
        *rows,
        "",
    ])


def _print_banner(dragon_color=None):
    R = dragon_color if dragon_color else "\033[31m"
    Y = "[33m"
    X = "[0m"

    lines = [
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡤⢴⣾⠟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡤⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⡤⠴⠚⠉⢀⡴⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡤⣾⠟⠀⠀⣀⣤⣾⣿⣟⣁⠤⠴⠒⠋⠉⠀⠀⢀⣠⠞⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣠⠴⢚⣁⣴⠧⠔⢚⣹⠿⠟⠛⠉⠁⠀⠀⠀⠀⠀⢀⣠⠖⠋⠀⠀⠀⠀⠄⠀⠀⠀⠀⠀⠀⣀⣀⣀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣠⠴⠚⣩⠔⠋⠉⠀⠀⠐⠊⠉⠀⢀⠀⠀⠀⠀⠀⠀⢀⣠⠔⠛⠛⠋⠉⠉⠉⠉⠉⠉⠉⠉⠉⠉⣉⡭⠟⠛⠉⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡤⠞⠋⣟⡡⠶⠛⠒⠚⠉⠀⠀⠀⠀⠀⠀⡰⠋⠀⠀⠀⠀⢠⡖⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡤⠴⠒⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡤⠖⠋⣀⣴⣋⠥⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⠞⠀⣀⠤⠖⠒⠒⠿⢤⣀⡀⠀⠀⠀⠀⠀⣠⠴⠚⠛⠓⠦⠤⢤⣀⣀⣀⡀⠀⠀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⢠⡖⠋⠀⣠⠖⠋⠁⠀⠀⠀⢀⡀⠀⠀⠀⠀⢀⣀⠤⠞⠁⠀⠉⠀⠀⠀⠀⢀⣀⣀⠀⠉⠙⠒⠦⢴⣋⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣈⣭⠽⠿⠟⠓⠀⠀⠀",
    ]
    eye_lines = [
        "⠀⠀⠀⠀⠀⠀⠀⢀⣸⣧⠀⢸⡁⠀⠀⣠⣴⣲⣶⡏⠀⢀⡠⠖⠊⠉⠀⠀⠀⠀⠀⠀⠀⣼⡟⠉⠁⠀⠈⠉⠉⠒⠲⢤⣀⠈⠙⠲⢤⣀⣀⡤⠴⠶⠯⣅⣀⠀⠀⠀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⣀⣠⡴⠒⠉⠁⠀⢀⡤⠛⠓⠋⠙⠻⠿⠋⢀⡴⠋⢀⡤⠒⠒⠤⣄⣠⡀⠀⠀⠀⣯⠙⠦⣄⠀⠀⠀⠀⠀⠀⠀⠈⠙⠲⠤⣀⣈⣉⣓⣦⣄⡀⠀⠀⠉⠓⠦⣄⡀⠀⠀⠀",
    ]
    rest = [
        "⠀⠀⣰⣿⡟⢠⣿⣙⡓⢦⡅⠀⠀⠀⠀⣀⡤⠤⢴⠋⣸⡟⡏⠀⠀⠀⠀⠀⠙⠁⠀⠀⠀⠘⣷⠤⣈⠑⠦⣄⠀⠀⠀⠀⠀⠀⣠⣶⣚⠉⠁⠀⢈⣉⢭⣷⡶⠔⠒⠒⠚⠛⠓⠀⠀",
        "⠀⣼⣿⠟⢀⣴⠋⢁⡖⠉⢀⡤⠖⡒⠉⢁⣄⣀⣾⠖⣇⣷⣇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣼⠀⠈⠑⠦⣀⠙⢦⡀⠀⣄⣠⡟⠳⣝⣦⠀⠀⠀⠙⠦⡈⠓⢤⡀⠀⠀⠀⠀⠀⠀",
        "⣼⣟⢉⣤⢸⣇⣀⣈⡀⠀⢀⣤⢰⣷⡤⣾⢻⣙⣟⣷⡟⠉⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣰⢿⠀⠀⠀⠀⠈⠳⠄⠘⢦⡀⢻⠁⠀⠀⠙⢷⡘⢦⣀⠀⠈⢦⡀⠙⢦⡀⠀⠀⠀⠀",
        "⣧⣿⣿⣧⡾⣏⢹⣿⣹⣿⣿⣇⢸⡿⣇⣿⡼⠻⠏⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣴⠃⠈⡆⠀⠀⠀⠀⠀⠀⠘⢦⠹⣾⠀⠀⠀⠀⠀⠑⠀⠈⠉⠲⣼⣿⣦⣄⠹⣄⠀⠀⠀",
        "⠈⢿⣿⣟⣧⠘⢾⣮⢿⣿⢿⡟⢿⠟⠉⠛⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣠⠞⠹⡄⠀⡇⠀⢀⡤⠖⠒⠲⠤⣄⣳⣼⣇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠻⣿⣯⡙⢾⣆⠀⠀",
        "⠀⠀⣻⢯⠛⠅⢀⡄⠀⠀⠀⠀⠀⠀⠀⠀⢀⡤⠀⣀⣀⣀⠀⠀⠀⠀⠀⠀⣠⣞⡁⠀⠀⢇⠀⣇⡴⠋⠀⠀⠀⠀⠀⠀⠈⠻⣿⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⢻⡻⣄⠉⢧⡀",
        "⠀⢠⡇⠀⠙⡶⠃⠀⢀⡖⠀⢰⠀⢠⢶⣴⡿⠚⠛⠻⢥⣉⠉⠓⠲⠦⠴⠚⠉⠀⠉⠙⢦⣸⠀⡿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠁⠈⢧⡀⠀",
        "⠀⣸⠀⢀⡠⢿⠀⠀⡼⣧⠀⡼⢷⡾⠀⠙⠃⠀⠀⠀⠀⠉⠳⣦⡀⠀⠀⠀⠀⠀⠀⠀⠀⣯⣸⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⣿⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠳⡀",
        "⠀⣇⡴⠋⠀⢸⢀⡼⠁⠈⠻⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠻⢦⡀⠀⠀⠀⠀⠀⠀⣿⠇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⢳⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠹",
        "⠀⠋⠀⠀⠀⠘⡟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢦⣄⠀⠀⠀⢰⡟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢧⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀",
        "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⣛⢦⣤⣈⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠘⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀",
    ]

    B = chr(92)
    NL = chr(10)
    logo = (
        " __    __ _   _ _ __  _ __ ___ _   _  __ _  __ _  ____  __" + NL +
        " " +B+B+" "+B+B+"/"+B+"/ /| | | || '__|  '_ ` _ "+B+" | | |/ _` |/ _` ||_  / / _ "+B + NL +
        "  "+B+" /"+B+" / | |_| || |   | | | | | || |_| (_| | (_| | / / |  __/" + NL +
        "   "+B+"/"+B+"/   "+B+"__, ||_|   |_| |_| |_| "+B+"__, |"+B+"__,_|"+B+"__,_|/___|"+B+"___|" + NL +
        "            |___/                     |___/" + NL +
        "      [ pentest action graph generator ]"
    )

    print(R + NL.join(lines))
    # color only the eye characters yellow, rest stays red
    eye1 = '\u28e0\u28f4\u28f2\u28f6\u284f'
    eye2 = '\u280b\u2819\u283b\u283f\u280b'
    def color_eye(line, eye):
        idx = line.find(eye)
        if idx < 0: return R + line
        return R + line[:idx] + Y + eye + R + line[idx+len(eye):]
    print(color_eye(eye_lines[0], eye1))
    print(color_eye(eye_lines[1], eye2))
    print(R + NL.join(rest) + X)
    print(R + logo + X)



def main():
    parser = argparse.ArgumentParser(description="wyrmgaze - pentest action graph generator")
    parser.add_argument("input", nargs="?", default="-",
                        help="Input file or '-' for stdin")
    COLORS = {
        "red":     "\033[31m",
        "green":   "\033[32m",
        "blue":    "\033[34m",
        "magenta": "\033[35m",
        "cyan":    "\033[36m",
        "white":   "\033[37m",
    }
    parser.add_argument(
        "--color", default="red", choices=COLORS.keys(),
        help="Dragon color: red (default), green, blue, magenta, cyan, white"
    )
    args = parser.parse_args()

    if args.input == "-":
        lines = sys.stdin.read().splitlines()
        stem  = "graph"
    else:
        lines = Path(args.input).read_text().splitlines()
        stem  = Path(args.input).stem

    actions = parse_actions(lines)
    if not actions:
        print("No valid actions found.", file=sys.stderr)
        sys.exit(1)

    color_map = assign_colors(actions)

    out_dir = Path(stem)
    out_dir.mkdir(exist_ok=True)

    layouts = [
        ("horizontal", generate_horizontal),
        ("vertical",   generate_vertical),
        ("hybrid",     generate_hybrid),
    ]

    w_num    = 3
    w_inputs = max(len("inputs"),  max(len(", ".join(a["inputs"]))  for a in actions))
    w_action = max(len("action"),  max(len(a["action"])              for a in actions))
    w_results= max(len("results"), max(len(", ".join(a["results"])) for a in actions))
    sep  = f"+{'-'*(w_num+2)}+{'-'*(w_inputs+2)}+{'-'*(w_action+2)}+{'-'*(w_results+2)}+"
    head = f"| {'#'.ljust(w_num)} | {'inputs'.ljust(w_inputs)} | {'action'.ljust(w_action)} | {'results'.ljust(w_results)} |"



    _print_banner(COLORS[args.color])
    print(f"  output dir : {out_dir}/")
    print(f"  actions    : {len(actions)}")
    print()

    layouts_files = []
    for layout, generator in layouts:
        svg_path = out_dir / f"{stem}_{layout}.svg"
        svg_w, svg_h, parts = generator(actions, color_map)
        svg_path.write_text(wrap_svg(svg_w, svg_h, parts), encoding="utf-8")
        layouts_files.append((layout, svg_path.name))
        print(f"  [{layout}] svg : {svg_path}")

    md_path = out_dir / f"{stem}.md"
    md_path.write_text(generate_markdown(actions, layouts_files), encoding="utf-8")
    print(f"  [markdown]  md  : {md_path}")
    print()
    print(sep)
    print(head)
    print(sep)
    for i, a in enumerate(actions, 1):
        print(f"| {str(i).ljust(w_num)} | {', '.join(a['inputs']).ljust(w_inputs)} | {a['action'].ljust(w_action)} | {', '.join(a['results']).ljust(w_results)} |")
    print(sep)
    print()


if __name__ == "__main__":
    main()
