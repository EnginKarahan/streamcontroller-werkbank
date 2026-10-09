// Werkbank Auto Page: tell StreamController about the active window.
//
// Event driven: one D-Bus call when a window is activated, and one when the
// active window's title changes (e.g. switching to a browser tab with a web
// meeting), nothing in between. Terminals are excluded from title tracking:
// they retitle several times a second (e.g. Claude Code's spinner) and would
// flood the bus. StreamController's auto page switching then matches
// class/title as usual.
var NO_TITLE_TRACKING = ["kitty", "konsole", "org.kde.konsole", "alacritty", "foot"];

var current = null;
var lastSent = "";

function notify(w) {
    var key = String(w.resourceClass) + "\n" + String(w.caption);
    if (key === lastSent) return;
    lastSent = key;
    callDBus("com.core447.StreamController", "/com/core447/StreamController",
             "com.core447.StreamController", "NotifyForegroundWindow",
             String(w.caption), String(w.resourceClass));
}

function onCaptionChanged() {
    if (current) notify(current);
}

function onActivated(w) {
    if (current) {
        try { current.captionChanged.disconnect(onCaptionChanged); } catch (e) {}
    }
    current = (w && w.normalWindow) ? w : null;
    if (!current) return;
    notify(current);
    if (NO_TITLE_TRACKING.indexOf(String(current.resourceClass).toLowerCase()) < 0) {
        current.captionChanged.connect(onCaptionChanged);
    }
}

workspace.windowActivated.connect(onActivated);
