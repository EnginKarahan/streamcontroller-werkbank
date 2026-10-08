// Werkbank Auto Page: tell StreamController about the active window.
//
// Event driven: one D-Bus call per window activation, nothing in between.
// Title changes are deliberately ignored: terminals (e.g. Claude Code's
// spinner) retitle several times a second and would flood the bus.
// StreamController's auto page switching then matches class/title as usual.
function notify(w) {
    if (!w || !w.normalWindow) return;
    callDBus("com.core447.StreamController", "/com/core447/StreamController",
             "com.core447.StreamController", "NotifyForegroundWindow",
             String(w.caption), String(w.resourceClass));
}

workspace.windowActivated.connect(notify);
