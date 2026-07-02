# -*- coding: utf-8 -*-
"""
Object-to-Face Level Shader Converter for Maya
Author  : Prem Kumar Mahato
Date    : 20/04/2026
Compatible : Python 2.7 (Maya 2020-) and Python 3 (Maya 2022+)
Purpose    : Converts object-level shader to face-level shader,
             with stable material slot ordering for Unreal Engine compatibility.

Usage (Script Editor):
    copy and paste the shader_face_converter.py file to "C:\\Users\\UserName\\Documents\\maya\\Version\\scripts"

    import shader_face_converter as sfc
    sfc.show_ui()
"""

from __future__ import print_function, division, absolute_import

import re
from collections import OrderedDict

import maya.cmds as cmds


# ---------------------------------------------------------------------------
# Compatibility helpers
# ---------------------------------------------------------------------------

def _fmt(template, *args, **kwargs):
    """
    Drop-in for f-strings -- works in Python 2.7 and 3.
    Usage:  _fmt("hello {0}", "world")
            _fmt("hello {name}", name="world")
    """
    return template.format(*args, **kwargs)


def _dedupe_ordered(seq):
    """Deduplicate a list while preserving insertion order (Py 2/3 safe)."""
    seen = set()
    out  = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------

def get_mesh_transforms(selection_only=True):
    """Return a list of transform nodes that own mesh shapes."""
    if selection_only:
        sel = cmds.ls(selection=True, long=True, type="transform") or []
        if not sel:
            raw = cmds.ls(selection=True, long=True) or []
            sel = []
            for s in raw:
                if cmds.objectType(s) == "mesh":
                    parents = cmds.listRelatives(s, parent=True, fullPath=True)
                    if parents:
                        sel.append(parents[0])
    else:
        shapes = cmds.ls(type="mesh", long=True, noIntermediate=True) or []
        seen   = set()
        sel    = []
        for s in shapes:
            parents = cmds.listRelatives(s, parent=True, fullPath=True)
            if parents and parents[0] not in seen:
                seen.add(parents[0])
                sel.append(parents[0])

    result = []
    for t in sel:
        shapes = cmds.listRelatives(t, shapes=True, type="mesh",
                                    fullPath=True, noIntermediate=True) or []
        if shapes:
            result.append(t)
    return result


def get_shading_data(mesh_shape):
    """
    Returns:
        (OrderedDict { sg_name: set_of_face_indices }, has_object_level)

    has_object_level is True if ANY SG is assigned at object level (whole mesh),
    meaning the mesh needs conversion even if it only has one material.
    Keys are ordered by first face index (stable UE slot order).
    """
    sgs = _dedupe_ordered(
        cmds.listConnections(mesh_shape, type="shadingEngine") or []
    )

    face_map         = {}
    has_object_level = False
    mesh_base        = mesh_shape.split("|")[-1]
    face_count       = cmds.polyEvaluate(mesh_shape, face=True)

    for sg in sgs:
        members      = cmds.sets(sg, query=True) or []
        face_indices = set()

        for member in members:
            member_base = member.split("|")[-1]
            if mesh_base not in member_base and mesh_shape not in member:
                continue

            if ".f[" in member:
                for match in re.finditer(r"f\[(\d+)(?::(\d+))?\]", member):
                    start = int(match.group(1))
                    end   = int(match.group(2)) if match.group(2) else start
                    face_indices.update(range(start, end + 1))
            else:
                has_object_level = True
                face_indices.update(range(face_count))

        if face_indices:
            if sg not in face_map:
                face_map[sg] = set()
            face_map[sg].update(face_indices)

    sorted_sgs = sorted(face_map.items(), key=lambda kv: min(kv[1]))
    return OrderedDict(sorted_sgs), has_object_level


def build_face_component_string(mesh_shape, face_indices):
    """Convert a set of face indices to compact Maya component strings."""
    indices = sorted(face_indices)
    if not indices:
        return []

    components = []
    start = prev = indices[0]
    for idx in indices[1:]:
        if idx == prev + 1:
            prev = idx
        else:
            if start == prev:
                components.append(_fmt("{0}.f[{1}]", mesh_shape, start))
            else:
                components.append(_fmt("{0}.f[{1}:{2}]", mesh_shape, start, prev))
            start = prev = idx
    if start == prev:
        components.append(_fmt("{0}.f[{1}]", mesh_shape, start))
    else:
        components.append(_fmt("{0}.f[{1}:{2}]", mesh_shape, start, prev))
    return components


def _remove_mesh_from_sg(mesh_shape, mesh_transform, sg):
    """
    Remove mesh from a shading group.
    """
    members    = cmds.sets(sg, query=True) or []
    shape_base = mesh_shape.split("|")[-1]
    xform_base = mesh_transform.split("|")[-1]

    to_remove = []
    for m in members:
        base = m.split("|")[-1].split(".")[0]
        if base in (shape_base, xform_base):
            to_remove.append(m)

    for node in (mesh_shape, mesh_transform,
                 mesh_shape.split("|")[-1], mesh_transform.split("|")[-1]):
        if cmds.objExists(node):
            try:
                cmds.sets(node, remove=sg)
            except Exception:
                pass

    for item in to_remove:
        try:
            cmds.sets(item, remove=sg)
        except Exception:
            pass


def convert_to_face_shaders(mesh_transform, log_fn=None):
    """
    Convert object level shaders to face shaders.
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    shapes = cmds.listRelatives(mesh_transform, shapes=True, type="mesh",
                                fullPath=True, noIntermediate=True) or []
    if not shapes:
        return False, _fmt("No mesh shape found under {0}", mesh_transform)

    mesh_shape = shapes[0]
    _log(_fmt("Processing: {0}", mesh_transform))

    shading_data, has_object_level = get_shading_data(mesh_shape)

    if not shading_data:
        return False, _fmt("  No shading groups found on {0}", mesh_transform)

    if not has_object_level:
        _log("  Already face-level. Skipping.")
        return True, "Already face-level -- skipped."

    for sg in list(shading_data.keys()):
        _remove_mesh_from_sg(mesh_shape, mesh_transform, sg)

    remaining = cmds.listConnections(mesh_shape, type="shadingEngine") or []
    if remaining:
        _log(_fmt("  WARNING: Could not fully detach from: {0}", remaining))

    assigned_sgs = []
    for slot_idx, (sg, face_indices) in enumerate(shading_data.items()):
        components = build_face_component_string(mesh_shape, face_indices)
        if not components:
            _log(_fmt("  WARNING: No face components built for {0} -- skipping.", sg))
            continue

        failed = 0
        for comp in components:
            try:
                cmds.sets(comp, edit=True, forceElement=sg)
            except Exception as e:
                _log(_fmt("  WARNING: {0} -> {1} failed: {2}", comp, sg, e))
                failed += 1

        assigned_sgs.append(sg)
        status = _fmt("({0} faces, slot {1})", len(face_indices), slot_idx)
        if failed:
            _log(_fmt("  SG '{0}' {1} -- {2} component(s) failed", sg, status, failed))
        else:
            _log(_fmt("  SG '{0}' {1}", sg, status))

    return True, _fmt("Converted {0} SG(s) to face-level on {1}",
                      len(assigned_sgs), mesh_transform)


def clean_unused_shading_groups(log_fn=None):
    """
    Delete shading groups (and their shaders) that have no members.
    Skips Maya defaults. Returns list of deleted nodes.
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    protected = {"initialShadingGroup", "initialParticleSE"}
    all_sgs   = cmds.ls(type="shadingEngine") or []
    deleted   = []

    for sg in all_sgs:
        if sg in protected:
            continue
        members = cmds.sets(sg, query=True) or []
        if not members:
            shader_nodes = []
            for attr in ("surfaceShader", "volumeShader", "displacementShader"):
                conn = cmds.listConnections(
                    _fmt("{0}.{1}", sg, attr), source=True, destination=False
                ) or []
                shader_nodes.extend(conn)

            try:
                cmds.delete(sg)
                deleted.append(sg)
                _log(_fmt("  Deleted unused SG: {0}", sg))
            except Exception as e:
                _log(_fmt("  Could not delete {0}: {1}", sg, e))
                continue

            for shader in shader_nodes:
                if cmds.objExists(shader):
                    try:
                        cmds.delete(shader)
                        _log(_fmt("    Deleted shader: {0}", shader))
                    except Exception:
                        pass

    return deleted


def run_conversion(selection_only=True, clean_unused=True, log_fn=None):
    """
        Headless entry point. Returns summary dict.
        Run without UI:
            import shader_face_converter_v04 as sfc
            sfc.run_conversion(selection_only=1, clean_unused=True)
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    meshes = get_mesh_transforms(selection_only=selection_only)
    if not meshes:
        _log("No valid meshes found.")
        return {"processed": 0, "failed": 0, "cleaned": 0}

    _log(_fmt("Found {0} mesh(es) to process.\n", len(meshes)))

    success_count = 0
    fail_count    = 0

    cmds.undoInfo(openChunk=True, chunkName="FaceShaderConvert")
    try:
        for mesh in meshes:
            ok, msg = convert_to_face_shaders(mesh, log_fn=log_fn)
            if ok:
                success_count += 1
            else:
                fail_count += 1
                _log(_fmt("  FAILED: {0}", msg))
            _log("")

        cleaned = 0
        if clean_unused:
            _log("Cleaning unused shading groups...")
            deleted = clean_unused_shading_groups(log_fn=log_fn)
            cleaned = len(deleted)
            _log(_fmt("  Removed {0} unused SG(s).\n", cleaned))

    finally:
        cmds.undoInfo(closeChunk=True)

    _log(_fmt("Done. Processed: {0} | Failed: {1} | Cleaned: {2}",
              success_count, fail_count, cleaned))
    return {"processed": success_count, "failed": fail_count, "cleaned": cleaned}


# ---------------------------------------------------------------------------
# Scene scanner (used by the UI Diagnose button)
# ---------------------------------------------------------------------------

def _scan_scene_for_object_level():
    """
    Get ALL meshes in scene.
    Returns list of dicts:
        { "transform": str, "shape": str, "sgs": [(sg_name, is_object_level), ...] }
    Only meshes with at least one object-level SG are returned.
    """
    results        = []
    all_transforms = get_mesh_transforms(selection_only=False)

    for xform in all_transforms:
        shapes = cmds.listRelatives(xform, shapes=True, type="mesh",
                                    fullPath=True, noIntermediate=True) or []
        if not shapes:
            continue
        shape      = shapes[0]
        sgs        = _dedupe_ordered(
            cmds.listConnections(shape, type="shadingEngine") or []
        )
        shape_base  = shape.split("|")[-1]
        sg_info     = []
        has_obj_lvl = False

        for sg in sgs:
            members = cmds.sets(sg, query=True) or []
            is_obj  = False
            for m in members:
                m_base = m.split("|")[-1].split(".")[0]
                if m_base == shape_base or shape in m:
                    if ".f[" not in m:
                        is_obj      = True
                        has_obj_lvl = True
                    break
            sg_info.append((sg, is_obj))

        if has_obj_lvl:
            results.append({
                "transform": xform,
                "shape":     shape,
                "sgs":       sg_info,
            })

    return results


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance
    import maya.OpenMayaUI as omui
    HAS_UI = True
except ImportError:
    HAS_UI = False


def _maya_main_window():
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QWidget)


STYLE = """
QWidget {
    background-color: #1a1a22;
    color: #d4d4d8;
    font-family: 'Segoe UI', Consolas, sans-serif;
    font-size: 12px;
}
QLabel#title {
    color: #f0f0f5;
    font-size: 15px;
    font-weight: bold;
    letter-spacing: 0.5px;
}
QLabel#subtitle { color: #3f3f52; font-size: 11px; }
QLabel#sec_label {
    color: #3f3f52;
    font-size: 9px;
    font-weight: bold;
    letter-spacing: 1.5px;
}
QPushButton#diag_btn {
    background-color: #1e1e2a;
    color: #a78bfa;
    border: 1px solid #3b2f6b;
    border-radius: 4px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton#diag_btn:hover  { background-color: #2a1e4a; border-color: #6d4fc9; }
QPushButton#diag_btn:pressed{ background-color: #1a1230; }
QPushButton#conv_sel_btn {
    background-color: #1e2a40;
    color: #60a5fa;
    border: 1px solid #1e3560;
    border-radius: 4px;
    padding: 7px 14px;
    font-weight: 600;
}
QPushButton#conv_sel_btn:hover   { background-color: #1e3060; border-color: #3b6ac9; }
QPushButton#conv_sel_btn:pressed { background-color: #162040; }
QPushButton#conv_sel_btn:disabled{ color: #2a3a50; border-color: #1a2030; }
QPushButton#conv_all_btn {
    background-color: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 7px 20px;
    font-size: 12px;
    font-weight: bold;
}
QPushButton#conv_all_btn:hover   { background-color: #2563eb; }
QPushButton#conv_all_btn:pressed { background-color: #1d4ed8; }
QPushButton#conv_all_btn:disabled{ background-color: #1e2a40; color: #3a4a60; }
QPushButton#sec_btn {
    background-color: #1e1e2a;
    color: #71717a;
    border: 1px solid #2a2a3a;
    border-radius: 4px;
    padding: 6px 12px;
}
QPushButton#sec_btn:hover { background-color: #2a2a3a; color: #a1a1b8; }
QCheckBox { color: #a1a1aa; spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #52525b;
    border-radius: 3px;
    background: #1e1e2a;
}
QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; }
QListWidget {
    background-color: #111118;
    border: 1px solid #1e1e2e;
    border-radius: 5px;
    color: #d4d4d8;
    font-family: Consolas, monospace;
    font-size: 11px;
    outline: none;
}
QListWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid #1a1a24;
}
QListWidget::item:selected {
    background-color: #1e2a40;
    color: #93c5fd;
    border-bottom-color: #1e2a40;
}
QListWidget::item:hover:!selected { background-color: #18181f; }
QPlainTextEdit {
    background-color: #0d0d12;
    color: #86efac;
    border: 1px solid #1a1a24;
    border-radius: 4px;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 11px;
    padding: 6px;
}
QFrame#sep { background-color: #1e1e2e; max-height: 1px; }
QLabel#status_ok  { color: #4ade80; font-weight: bold; font-size: 11px; }
QLabel#status_err { color: #f87171; font-weight: bold; font-size: 11px; }
QLabel#status_idle{ color: #52525b; font-size: 11px; }
"""


class MeshListItem(QtWidgets.QListWidgetItem):
    """List item that carries the full transform path."""
    def __init__(self, transform_path, sg_count):
        short = transform_path.split("|")[-1]
        label = _fmt("  {0}  ({1} SG{2})",
                     short, sg_count, "s" if sg_count != 1 else "")
        QtWidgets.QListWidgetItem.__init__(self, label)
        self.transform_path = transform_path
        self.sg_count       = sg_count


class ShaderConverterUI(QtWidgets.QDialog):
    def __init__(self, parent=None):
        QtWidgets.QDialog.__init__(self, parent or _maya_main_window())
        self.setWindowTitle("Face Level Shader Converter")
        self.setMinimumWidth(500)
        self.setMinimumHeight(560)
        self.setStyleSheet(STYLE)
        self._scanned_meshes = []
        self._build_ui()
        self._refresh_convert_buttons()

    # ------------------------------------------------------------------
    def _sep(self):
        f = QtWidgets.QFrame()
        f.setObjectName("sep")
        f.setFrameShape(QtWidgets.QFrame.HLine)
        return f

    def _sec_label(self, text):
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("sec_label")
        return lbl

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # Header
        title = QtWidgets.QLabel("Face Level Shader Converter")
        title.setObjectName("title")
        sub = QtWidgets.QLabel(
            "Detect & fix object-level shader assignments  |  UE-stable slot order"
        )
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)
        root.addWidget(self._sep())

        # Step 1 -- Diagnose
        root.addWidget(self._sec_label("STEP 1 -- DIAGNOSE (For object level shaders)"))
        diag_row = QtWidgets.QHBoxLayout()
        self.diag_btn = QtWidgets.QPushButton("  Diagnose Scene")
        self.diag_btn.setObjectName("diag_btn")
        self.diag_btn.setToolTip(
            "Scan all meshes in scene and list those with object-level shader assignments"
        )
        self.mesh_count_lbl = QtWidgets.QLabel("No scan yet.")
        self.mesh_count_lbl.setObjectName("status_idle")
        diag_row.addWidget(self.diag_btn)
        diag_row.addSpacing(10)
        diag_row.addWidget(self.mesh_count_lbl)
        diag_row.addStretch()
        root.addLayout(diag_row)

        # Mesh list
        root.addWidget(self._sec_label("MESHES WITH OBJECT-LEVEL SHADERS"))
        self.mesh_list = QtWidgets.QListWidget()
        self.mesh_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.mesh_list.setMinimumHeight(160)
        self.mesh_list.setToolTip(
            "Click to select  |  Ctrl/Shift for multi-select\n"
            "Double-click to select in the Maya viewport"
        )
        root.addWidget(self.mesh_list)

        # Option
        self.cb_clean = QtWidgets.QCheckBox(
            "Clean unused shading groups after conversion"
        )
        self.cb_clean.setChecked(True)
        root.addWidget(self.cb_clean)
        root.addWidget(self._sep())

        # Step 2 -- Convert
        root.addWidget(self._sec_label("STEP 2 -- CONVERT TO FACE LEVEL SHADERS"))
        conv_row = QtWidgets.QHBoxLayout()
        self.conv_sel_btn = QtWidgets.QPushButton("  Convert Selected")
        self.conv_sel_btn.setObjectName("conv_sel_btn")
        self.conv_sel_btn.setToolTip(
            "Convert only the meshes selected in the list above"
        )
        self.conv_all_btn = QtWidgets.QPushButton("  Convert All Listed")
        self.conv_all_btn.setObjectName("conv_all_btn")
        self.conv_all_btn.setToolTip("Convert every mesh shown in the list")
        conv_row.addWidget(self.conv_sel_btn)
        conv_row.addWidget(self.conv_all_btn)
        root.addLayout(conv_row)

        # Log
        root.addWidget(self._sep())
        root.addWidget(self._sec_label("LOG"))
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(120)
        self.log.setPlaceholderText("Run Diagnose first, then Convert...")
        root.addWidget(self.log)

        # Status + clear
        bot_row = QtWidgets.QHBoxLayout()
        self.status_lbl = QtWidgets.QLabel("")
        self.status_lbl.setObjectName("status_idle")
        self.clear_btn = QtWidgets.QPushButton("Clear Log")
        self.clear_btn.setObjectName("sec_btn")
        bot_row.addWidget(self.status_lbl, stretch=1)
        bot_row.addWidget(self.clear_btn)
        root.addLayout(bot_row)

        # Signal connections
        self.diag_btn.clicked.connect(self._on_diagnose)
        self.conv_sel_btn.clicked.connect(self._on_convert_selected)
        self.conv_all_btn.clicked.connect(self._on_convert_all)
        self.clear_btn.clicked.connect(self.log.clear)
        self.mesh_list.itemSelectionChanged.connect(self._refresh_convert_buttons)
        self.mesh_list.itemDoubleClicked.connect(self._on_item_double_click)

    # ------------------------------------------------------------------
    def _append(self, msg):
        self.log.appendPlainText(msg)
        QtWidgets.QApplication.processEvents()

    def _set_status(self, msg, kind="idle"):
        names = {"ok": "status_ok", "err": "status_err", "idle": "status_idle"}
        self.status_lbl.setObjectName(names.get(kind, "status_idle"))
        self.status_lbl.setText(msg)
        self.status_lbl.style().unpolish(self.status_lbl)
        self.status_lbl.style().polish(self.status_lbl)

    def _refresh_convert_buttons(self):
        has_items    = self.mesh_list.count() > 0
        has_selected = len(self.mesh_list.selectedItems()) > 0
        self.conv_all_btn.setEnabled(has_items)
        self.conv_sel_btn.setEnabled(has_selected)

    # ------------------------------------------------------------------
    def _on_diagnose(self):
        self.mesh_list.clear()
        self.log.clear()
        self._set_status("Scanning...", "idle")
        QtWidgets.QApplication.processEvents()

        self._scanned_meshes = _scan_scene_for_object_level()

        if not self._scanned_meshes:
            self.mesh_count_lbl.setObjectName("status_ok")
            self.mesh_count_lbl.setText("All meshes are already face-level")
            self.mesh_count_lbl.style().unpolish(self.mesh_count_lbl)
            self.mesh_count_lbl.style().polish(self.mesh_count_lbl)
            self._set_status("Nothing to convert.", "ok")
            self._append("Diagnose: No object-level shader assignments found in scene.")
        else:
            n = len(self._scanned_meshes)
            self.mesh_count_lbl.setObjectName("status_err")
            self.mesh_count_lbl.setText(
                _fmt("{0} mesh{1} need conversion", n, "es" if n != 1 else "")
            )
            self.mesh_count_lbl.style().unpolish(self.mesh_count_lbl)
            self.mesh_count_lbl.style().polish(self.mesh_count_lbl)

            for entry in self._scanned_meshes:
                item = MeshListItem(entry["transform"], len(entry["sgs"]))
                self.mesh_list.addItem(item)

            self._append(
                _fmt("Diagnose: found {0} mesh(es) with object-level shader assignments:\n", n)
            )
            for entry in self._scanned_meshes:
                short = entry["transform"].split("|")[-1]
                self._append(_fmt("  {0}", short))
                for sg_name, is_obj in entry["sgs"]:
                    tag = "OBJECT-LEVEL  [needs fix]" if is_obj else "face-level  [ok]"
                    self._append(_fmt("      {0}  ->  {1}", sg_name, tag))

            self._set_status(
                _fmt("Found {0} mesh(es) to fix. Select from list or Convert All.", n),
                "idle"
            )

        self._refresh_convert_buttons()

    # ------------------------------------------------------------------
    def _on_item_double_click(self, item):
        """Select the mesh in the Maya viewport on double-click."""
        try:
            cmds.select(item.transform_path, replace=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _run_on_transforms(self, transforms):
        self.log.clear()
        clean   = self.cb_clean.isChecked()
        success = fail = cleaned = 0

        cmds.undoInfo(openChunk=True, chunkName="FaceShaderConvert")
        try:
            for xform in transforms:
                ok, msg = convert_to_face_shaders(xform, log_fn=self._append)
                if ok:
                    success += 1
                else:
                    fail += 1
                    self._append(_fmt("  FAILED: {0}", msg))
                self._append("")

            if clean:
                self._append("Cleaning unused shading groups...")
                deleted = clean_unused_shading_groups(log_fn=self._append)
                cleaned = len(deleted)
                self._append(_fmt("  Removed {0} SG(s).\n", cleaned))
        finally:
            cmds.undoInfo(closeChunk=True)

        kind = "ok" if fail == 0 else "err"
        self._set_status(
            _fmt("{0} converted, {1} failed, {2} SG(s) cleaned.",
                 success, fail, cleaned),
            kind
        )
        # Re-diagnose so list reflects current state
        self._on_diagnose()

    # ------------------------------------------------------------------
    def _on_convert_selected(self):
        selected_items = self.mesh_list.selectedItems()
        if not selected_items:
            self._set_status("Select at least one mesh from the list.", "idle")
            return
        transforms = [item.transform_path for item in selected_items]
        self._run_on_transforms(transforms)

    def _on_convert_all(self):
        if not self._scanned_meshes:
            self._set_status("Run Diagnose first.", "idle")
            return
        transforms = [e["transform"] for e in self._scanned_meshes]
        self._run_on_transforms(transforms)


# ---------------------------------------------------------------------------
# Show UI
# ---------------------------------------------------------------------------

_ui_instance = None


def show_ui():
    global _ui_instance
    if _ui_instance is not None:
        try:
            _ui_instance.close()
        except Exception:
            pass
    if not HAS_UI:
        raise RuntimeError("""
        PySide2 not available. Run headlessly via run_conversion():
        
        # Run:
        import shader_face_converter as sfc
        sfc.run_conversion(selection_only=1, clean_unused=True)
        """)
    _ui_instance = ShaderConverterUI()
    _ui_instance.show()
    return _ui_instance


# ---------------------------------------------------------------------------
# Diagnostic helper (Script Editor / headless)
# ---------------------------------------------------------------------------

def diagnose(selection_only=True):
    """
    Print whether each SG is object-level or face-level for selected meshes.

    Example:
        import shader_face_converter as sfc
        sfc.diagnose()          # before
        sfc.run_conversion()
        sfc.diagnose()          # after -- should show face-level for all
    """
    meshes = get_mesh_transforms(selection_only=selection_only)
    if not meshes:
        print("diagnose: No meshes found.")
        return

    for xform in meshes:
        shapes = cmds.listRelatives(xform, shapes=True, type="mesh",
                                    fullPath=True, noIntermediate=True) or []
        if not shapes:
            continue
        shape      = shapes[0]
        sgs        = _dedupe_ordered(
            cmds.listConnections(shape, type="shadingEngine") or []
        )
        shape_base = shape.split("|")[-1]
        print(_fmt("\n{0}", xform))
        for sg in sgs:
            members = cmds.sets(sg, query=True) or []
            for m in members:
                if shape_base in m or shape in m:
                    if ".f[" in m:
                        print(_fmt("  [{0}]  FACE-LEVEL   [ok]          ({1})", sg, m))
                    else:
                        print(_fmt("  [{0}]  OBJECT-LEVEL [needs fix]   ({1})", sg, m))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    show_ui()
