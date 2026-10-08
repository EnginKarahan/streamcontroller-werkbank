// Switches to virtual desktop number p.number (1-based) and reports it.
(function () {
    var p = __PARAMS__;
    var list = workspace.desktops;
    var out = null;
    if (p.number >= 1 && p.number <= list.length) {
        workspace.currentDesktop = list[p.number - 1];
        out = { number: p.number, name: String(list[p.number - 1].name) };
    }
    callDBus("__SINK__", "/Sink", "io.github.EnginKarahan.Werkbank.Sink", "Push", JSON.stringify(out));
})();
