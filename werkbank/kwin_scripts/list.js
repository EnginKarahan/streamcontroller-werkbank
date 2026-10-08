// Reports all normal windows to the Werkbank receiver.
(function () {
    var out = [];
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (!w.normalWindow || w.skipTaskbar) continue;
        out.push({
            resourceClass: String(w.resourceClass),
            resourceName: String(w.resourceName),
            caption: String(w.caption),
            pid: w.pid,
            active: w.active === true
        });
    }
    callDBus("__SINK__", "/Sink", "io.github.EnginKarahan.Werkbank.Sink", "Push", JSON.stringify(out));
})();
