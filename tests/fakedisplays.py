"""Made-up monitor layouts for tests (nothing here asks Windows). A FakeDisplays has the same interface as
displays.Displays (monitors / probe / commit) plus `set(layout)` to simulate a monitor going or coming back, and
FakeClock for the 3 s settle time."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import displays  # noqa: E402

M = displays.monitor

# A typical 3-monitor setup (the layout EnumDisplayMonitors reported on a real machine): three 1920x1080 monitors side by side,
# the middle one primary, a 48 px taskbar on each (rcWork bottom 1032).
LEFT = M((-1920, 0, 0, 1080), (-1920, 0, 0, 1032))
MIDDLE = M((0, 0, 1920, 1080), (0, 0, 1920, 1032), True)
RIGHT = M((1920, 0, 3840, 1080), (1920, 0, 3840, 1032))
THREE = [MIDDLE, LEFT, RIGHT]
TWO_LEFT = [MIDDLE, LEFT]
ONE = [MIDDLE]
# not side by side at the same height: a small monitor on the right, shifted down -> dead areas
MISALIGNED = [M((0, 0, 1920, 1080), (0, 0, 1920, 1032), True), M((1920, 400, 3200, 1120), (1920, 400, 3200, 1120))]


class FakeDisplays:
    def __init__(self, layout=THREE):
        self.system = list(layout)         # what "Windows" says right now
        self.committed = list(layout)      # what the app uses
        self.fail = False                  # True: the system cannot say

    def set(self, layout):
        self.system = list(layout)

    def monitors(self):
        return self.committed

    def probe(self):
        return None if self.fail else list(self.system)

    def commit(self, mons):
        self.committed = list(mons)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s
