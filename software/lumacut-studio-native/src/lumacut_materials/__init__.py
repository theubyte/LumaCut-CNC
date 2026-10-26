"""Materialbibliothek für LumaCut Studio (Diodenlaser 450 nm).

Qt-freier Kern:

* :mod:`.db`        – Materialdatenbank (``materials.json``) und Laserprofile
* :mod:`.planner`   – Schneid-/Gravur-/Reliefplanung (Durchgänge, Tiefe, Z-Absenkung)
* :mod:`.heightmap` – Höhenkarte aus Bild (Graustufen, Gamma, Kontrast, Glätten)
* :mod:`.relief`    – G-Code für 3D-Relief (Pi-/Marlin-Inline-Regeln)
* :mod:`.presets`   – speicherbare Voreinstellungen, Anwenden auf Ebenen
* :mod:`.link`      – Ebene verknüpfen/zuweisen, Neuplanung bei Dickenänderung
* :mod:`.process`   – Kerf/Stegbreite/Anfahrt-Startwerte je Material
* :mod:`.testgrid`  – Materialtest-Zelle → eigenes Preset
* :mod:`.depth3d`   – Reliefplan → Bild-Modus ``depth3d``

Die Qt-Oberfläche liegt getrennt in :mod:`.dialog`.

Alle Werte sind **Startwerte** aus Herstellertabellen und Skalierung,
nicht an der Maschine getestet – immer zuerst ein Testraster fahren.
"""

from .db import Laser, Material, MaterialDB, MaterialError, load_db
from .planner import (CutPlan, EngravePlan, ReliefPlan, engrave_levels, plan, plan_cut,
                      plan_engrave, plan_relief)
from .presets import Preset, PresetStore, make_preset
from .link import install_link_hook, plan_layer_attrs
from .process import ProcessDefaults, process_defaults
from .testgrid import preset_from_test_cell
from .depth3d import depth3d_image_settings

__all__ = ["Laser", "Material", "MaterialDB", "MaterialError", "load_db", "CutPlan",
           "EngravePlan", "ReliefPlan", "engrave_levels", "plan", "plan_cut", "plan_engrave",
           "plan_relief", "Preset", "PresetStore", "make_preset", "install_link_hook",
           "plan_layer_attrs", "ProcessDefaults", "process_defaults", "preset_from_test_cell",
           "depth3d_image_settings"]
