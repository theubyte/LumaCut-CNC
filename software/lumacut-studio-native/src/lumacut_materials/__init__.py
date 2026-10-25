"""Materialbibliothek für LumaCut Studio (Diodenlaser 450 nm).

Qt-freier Kern:

* :mod:`.db`        – Materialdatenbank (``materials.json``) und Laserprofile
* :mod:`.planner`   – Schneid-/Gravur-/Reliefplanung (Durchgänge, Tiefe, Z-Absenkung)
* :mod:`.heightmap` – Höhenkarte aus Bild (Graustufen, Gamma, Kontrast, Glätten)
* :mod:`.relief`    – G-Code für 3D-Relief (Pi-/Marlin-Inline-Regeln)
* :mod:`.presets`   – speicherbare Voreinstellungen, Anwenden auf Ebenen

Die Qt-Oberfläche liegt getrennt in :mod:`.dialog`.

Alle Werte sind **Startwerte** aus Herstellertabellen und Skalierung,
nicht an der Maschine getestet – immer zuerst ein Testraster fahren.
"""

from .db import Laser, Material, MaterialDB, MaterialError, load_db
from .planner import (CutPlan, EngravePlan, ReliefPlan, engrave_levels, plan, plan_cut,
                      plan_engrave, plan_relief)
from .presets import Preset, PresetStore, make_preset

__all__ = ["Laser", "Material", "MaterialDB", "MaterialError", "load_db", "CutPlan",
           "EngravePlan", "ReliefPlan", "engrave_levels", "plan", "plan_cut", "plan_engrave",
           "plan_relief", "Preset", "PresetStore", "make_preset"]
