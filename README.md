# Maya Face-Level Shader Converter (Unreal Pipeline Tool)

A pipeline utility built in Autodesk Maya to convert **object-level shader assignments** into **face-level assignments**, ensuring reliable material slot export in Unreal Engine.

> ⚠️ Note: This repository showcases the tool and workflow. Source code is intentionally kept private.

---

## 🚀 Overview

In Maya, shaders are often assigned at the object level. When exporting to Unreal Engine via FBX, this can lead to:

- Missing material slots
- Incorrect material assignments
- Inconsistent material behavior

This tool automates the conversion to **face-level assignments**, making assets **Unreal-ready**.

---

## 🎯 Key Features

- 🔍 Detects object-level shader assignments
- 🔁 Converts them into face-level assignments
- ⚡ Skips already valid meshes
- 🧹 Optional cleanup of unused shading groups
- 🖥️ Supports UI and headless workflows
- 🎯 Built for Maya → Unreal Engine pipeline

---

## 🧠 Problem → Solution

### Problem
Object-level shader assignments in Maya are not always interpreted correctly in Unreal Engine, especially for multi-material meshes.

### Solution
Convert all shader assignments to face-level before export to ensure:
- Proper material slot creation
- Correct material mapping in Unreal

---

## 🛠️ Workflow

1. Load scene in Maya
2. Run the tool
3. Diagnose shader assignments
4. Convert object-level → face-level
5. Export to FBX
6. Import into Unreal Engine with correct material slots

---

## 📸 Demo

*(Add your screenshots or GIF here)*

Suggested demo flow:
- Before: Object-level shader assignment
- Tool detects issue
- Conversion executed
- After: Clean face-level assignment
- Unreal import showing correct materials

---

## 🎯 Use Cases

- Technical Artists preparing assets for Unreal Engine
- Pipeline TDs building export workflows
- Asset teams working with multi-material meshes
- Game development pipelines using Maya + Unreal

---

## 🧱 Tech Stack

- Autodesk Maya (Python - `cmds`)
- PySide2 (UI)

---

## 💡 What This Demonstrates

This tool reflects:
- Pipeline problem-solving mindset
- Understanding of DCC → Game Engine workflows
- Automation of repetitive technical tasks
- Focus on production reliability

---

## 🔒 Source Code

The implementation is kept private.  
I’m happy to walk through the logic, design decisions, and edge cases during discussions or interviews.

---

## 👤 Author

Prem Kumar Mahato  
Rigging Artist | Technical Artist | Pipeline Enthusiast

---

## 🔗 Connect

https://www.linkedin.com/in/premkumarmahato/
