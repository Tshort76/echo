"""Desktop GUI for echo.

This package is a thin presentation layer on top of the ``echo`` backend. The
dependency direction is strictly one-way: the GUI imports the backend, never the
reverse. The backend remains a standalone CLI tool with no knowledge that a GUI
exists.

Launch with ``python echo_gui.py`` (requires ``pip install -r requirements-gui.txt``).
"""
