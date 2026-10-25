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

from .db import Laser, Material, MaterialDB, load_db
from .planner import (CutPlan, EngravePlan, ReliefPlan, engrave_levels, plan_cut,
                      plan_engrave, plan_relief)

__all__ = ["Laser", "Material", "MaterialDB", "load_db", "CutPlan", "EngravePlan",
           "ReliefPlan", "engrave_levels", "plan_cut", "plan_engrave", "plan_relief"]
