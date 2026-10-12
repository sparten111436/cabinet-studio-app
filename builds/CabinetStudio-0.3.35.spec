# -*- mode: python ; coding: utf-8 -*-
# Cabinet Studio 0.3.35 onedir (2026-10-12, template CabinetStudio-0.3.34.spec): starter cabinet templates + Start from a template gallery (services.starter_templates, ui.starter_gallery).
# 0.3.34b (2026-10-12): bundles the HTML user manual (cabinet_studio/docs) opened by "? Manual" / Help > User manual.
# Cabinet Studio 0.3.34 onedir (2026-10-12, template CabinetStudio-0.3.33.spec) - shareable build: saves fall back to Documents\Cabinet Studio off Warren's tree, version resource, no .bak/__pycache__ data.
# Previous: 0.3.33 onedir (built 2026-10-09 from mvp\, template CabinetStudio-0.3.27.spec) - hover help, pretend machine Normal run, light curtain + stack light, AB/Siemens/Omron library + maker preference, real outlines; right-click Copy/Paste/Delete/Add part on layout + door sheets; drag/drop layout + door parts, Reset layout, AI auto enclosure; - Each part / Normal run / Explain run sim, AI copy-paste, Groq + xAI, interview AI answers + door question, backplate power zones
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_dynamic_libs

datas = [('C:/Users/spart/OneDrive/Desktop/CabinetStudio/assets/cabinet_studio.ico', 'assets'), ('C:/Users/spart/OneDrive/Desktop/CabinetStudio/assets/cabinet_studio.ico', '.'), ('C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp/cabinet_studio/library', 'cabinet_studio/library'), ('C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp/cabinet_studio/programs', 'cabinet_studio/programs'), ('C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp/cabinet_studio/docs/Cabinet-Studio-User-Manual.html', 'cabinet_studio/docs')]
binaries = []
hiddenimports = ['cabinet_studio.services.sim_plant', 'cabinet_studio.ui.hover_tip', 'cabinet_studio.ui.rung_help', 'cabinet_studio.services.hmi_library', 'cabinet_studio.services.hmi_design', 'cabinet_studio.services.hmi_drawings', 'cabinet_studio.ui.hmi_editor', 'cabinet_studio.services.sim_autorun', 'cabinet_studio.services.sim_explain', 'cabinet_studio.services.panel_zones', 'cabinet_studio.ui.explain_run', 'cabinet_studio.services.ladder_sim', 'cabinet_studio.services.plcopen_xml', 'cabinet_studio.services.plcopen_graph', 'cabinet_studio.services.ladder_ir', 'cabinet_studio.services.ladder_print', 'cabinet_studio.services.ladder_tools', 'cabinet_studio.services.ladder_history', 'cabinet_studio.services.ladder_templates', 'cabinet_studio.services.programming', 'cabinet_studio.services.drawings', 'cabinet_studio.ui.programming_viewer', 'cabinet_studio.ui.drawing_viewer', 'cabinet_studio.ui.wizard', 'cabinet_studio.services.wiring_assist', 'cabinet_studio.services.wiring_assist_pc', 'cabinet_studio.services.standards', 'cabinet_studio.services.wizard_plan', 'cabinet_studio.services.suggestions', 'cabinet_studio.services.ai_build', 'cabinet_studio.services.ai_providers', 'cabinet_studio.services.ai_assist', 'cabinet_studio.ui.ai_build', 'cabinet_studio.ui.ai_settings', 'cabinet_studio.ui.ai_assistant', 'cabinet_studio.ui.ai_interview_hooks', 'cabinet_studio.ui.theme', 'cabinet_studio.ui.commands', 'cabinet_studio.ui.shell', 'cabinet_studio.ui.shell.main_shell', 'cabinet_studio.ui.shell.statusbar', 'cabinet_studio.ui.shell.sim_toolbar', 'cabinet_studio.ui.prefs', 'cabinet_studio.ui.shell.treeview', 'cabinet_studio.ui.shell.project_explorer', 'cabinet_studio.ui.studio', 'cabinet_studio.ui.studio.organizer', 'cabinet_studio.ui.studio.palette', 'cabinet_studio.ui.studio.properties', 'cabinet_studio.ui.studio.program_wizard', 'ssl', 'urllib.request']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += ['cabinet_studio.services.hmi_runtime', 'cabinet_studio.services.hmi_symbols',
                  'cabinet_studio.services.hmi_export', 'cabinet_studio.services.io_assign',
                  'cabinet_studio.services.io_drawings', 'cabinet_studio.services.plc_export',
                  'cabinet_studio.services.device_link', 'cabinet_studio.ui.device_panel', 'cabinet_studio.ui.manual',
                  'cabinet_studio.services.starter_templates', 'cabinet_studio.ui.starter_gallery']
hiddenimports += collect_submodules('pycomm3') + collect_submodules('snap7')
binaries += collect_dynamic_libs('snap7')

a = Analysis(['C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp/app.py'], pathex=['C:/Users/spart/OneDrive/Desktop/CabinetStudio/mvp'], binaries=binaries, datas=datas, hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
a.datas = [d for d in a.datas if '.bak' not in d[0] and '__pycache__' not in d[0]]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CabinetStudio', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False, icon='C:/Users/spart/OneDrive/Desktop/CabinetStudio/assets/cabinet_studio.ico', disable_windowed_traceback=False, argv_emulation=False, target_arch=None, version='C:/Users/spart/OneDrive/Desktop/CabinetStudio/builds/version_info_0.3.35.txt', codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, upx_exclude=[], name='CabinetStudio')


