import tkinter as tk
from tkinter import ttk


def _stylize() -> ttk.Style:
    # Define styles
    style = ttk.Style()
    style.theme_use("clam")  # Set the theme (e.g., 'clam' for modern look)

    # Customize widget styles
    style.configure(
        "TLabel",
        background="#2b2b2b",  # Label background
        foreground="#ffffff",  # Label text color
        padding=6,
    )

    style.configure(
        "TButton",
        background="#5a5a5a",  # Button background
        foreground="#ffffff",  # Button text color
        padding=6,
        borderwidth=2,
    )
    style.map(
        "TButton",
        background=[("active", "#767676")],  # Button color on hover
    )

    style.configure(
        "TFrame",
        background="#2b2b2b",  # Frame background
    )

    style.configure(
        "TOptionMenu",
        background="#5a5a5a",
        foreground="#ffffff",
    )


def initialize_frame() -> tuple[tk.Tk, ttk.Frame]:
    # Initialize the main window
    root = tk.Tk()
    root.title("Echoes")
    root.geometry("500x300")
    root.configure(bg="#2b2b2b")  # background color

    _stylize()

    # Create a main frame
    main_frame = ttk.Frame(root)
    main_frame.grid(padx=5, pady=5, sticky="NSEW")

    # Configure grid resizing
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    main_frame.columnconfigure(1, weight=1)

    return root, main_frame
