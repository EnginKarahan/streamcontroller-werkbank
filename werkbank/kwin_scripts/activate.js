// Activates the first normal window matching all given criteria and reports
// it (or null) to the Werkbank receiver. Minimised windows are restored.
(function () {
    var p = __PARAMS__;
    var cls = p.cls ? new RegExp(p.cls, "i") : null;
    var cap = p.caption ? new RegExp(p.caption, "i") : null;
    var hit = null;
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (!w.normalWindow || w.skipTaskbar) continue;
        if (cls && !cls.test(String(w.resourceClass)) && !cls.test(String(w.resourceName))) continue;
        if (cap && !cap.test(String(w.caption))) continue;
        if (p.pid && w.pid !== p.pid) continue;
        hit = w;
        break;
    }
    var out = null;
    if (hit) {
        if (hit.minimized) hit.minimized = false;
        workspace.activeWindow = hit;
        out = {
            resourceClass: String(hit.resourceClass),
            caption: String(hit.caption),
            pid: hit.pid
        };
    }
    callDBus("__SINK__", "/Sink", "io.github.EnginKarahan.Werkbank.Sink", "Push", JSON.stringify(out));
})();
