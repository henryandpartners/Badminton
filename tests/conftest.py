import os
import tempfile

# Isolate the UI render test on its own throwaway SQLite DB.
os.environ.setdefault(
    "DATABASE_URL", f"sqlite:///{os.path.join(tempfile.gettempdir(), 'ui_render_test.db')}"
)

pytest_plugins = ["nicegui.testing.user_plugin"]
