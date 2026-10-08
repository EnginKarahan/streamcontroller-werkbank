from .base import Field, WerkbankAction


class NewNote(WerkbankAction):
    """Create a Markdown note from a template and open it in the editor."""

    FIELDS = [
        Field("template", "Template file", subtitle="Markdown with front matter, e.g. ~/Notes/templates/zettel.md"),
        Field("directory", "Target folder"),
        Field("pattern", "File name", default="{title}.md",
              subtitle="placeholders: {title} {id} {date} {date_de} {time}"),
        Field("ask", "Ask for a title (prompt)", default="Title:",
              subtitle="leave empty for notes without a title, e.g. a daily journal"),
        Field("editor", "Open with", default="xdg-open"),
    ]
    DEFAULT_ICON = "document-new"

    def on_key_down(self):
        if self.setting("template") and self.setting("directory"):
            self.in_background(self.run)
        else:
            self.show_error(duration=2)

    def run(self):
        args = ["note", self.setting("template"), self.setting("directory"),
                "--name", self.setting("pattern") or "{title}.md"]
        if self.setting("ask"):
            args += ["--ask", self.setting("ask")]
        if self.setting("editor"):
            args += ["--open", self.setting("editor")]
        result = self.core(*args, timeout=600)  # the title dialog waits for the user
        if result.get("result") != "cancelled":
            self.report(result)
