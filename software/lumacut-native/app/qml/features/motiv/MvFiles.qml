import QtQml
import LumaCut

// What the file menu and its keys do. The work is in Sync, Editor and Document; every path-taking function there can be
// called directly (tests, whoever has a path).
QtObject {
    function run(action) {
        switch (action) {
        case "new":
            if (Document.dirty && !Document.empty) {
                Confirm.ask({ title: "Neues Projekt beginnen?", body: "Nicht gespeicherte Änderungen gehen verloren.", okLabel: "Neu beginnen", danger: true },
                            (yes) => { if (yes) Document.reset() })
            } else Document.reset()
            break
        case "open": Sync.openProjectDialog(); break
        case "openLocal": Sync.openLocal(); break
        case "save": Sync.saveProjectToPi(); break
        case "saveLocal": Sync.saveLocalAs(); break
        case "rename": Editor.dialog = "rename"; break
        case "import": Editor.askImport(); break
        case "export": Editor.dialog = "export"; break
        }
    }
}
