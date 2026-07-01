"""In-process render test for the NiceGUI app (no server/port needed).

Proves the page builds without serialization errors and shows key content.
"""

from nicegui.testing import User

import main  # noqa: F401  — importing registers the @ui.page routes


async def test_home_renders(user: User) -> None:
    await user.open("/")
    await user.should_see("Badminton Tracker")
    await user.should_see("Check-in")
