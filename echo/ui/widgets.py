import logging
import pprint
import tkinter as tk
from tkinter import filedialog, ttk

import echo.core as c
import echo.constants as cn

log = logging.getLogger(__name__)

widgets_state = {}


def _safe_int(var: tk.StringVar, default: int) -> int:
    x = var.get()
    if x is not None and x.isdigit():
        return int(x)
    return default


def _stripped_path(path: tk.StringVar) -> str:
    s = path.get().strip()
    if s and s.startswith("<"):
        return None
    return s


def _state_snapshot():
    kw_args = {
        "input_path": _stripped_path(widgets_state["input_file"]),
        "icon_path": _stripped_path(widgets_state["image_file"]),
        "process": widgets_state["process"].get(),
        "voice": widgets_state["voice"].get(),
        "starting_page": _safe_int(widgets_state["start_range"], 0),
        "ending_page": _safe_int(widgets_state["end_range"], 9999),
    }
    log.info(pprint.pformat(kw_args))
    output_path = c.convert(**kw_args)
    if output_path:
        c.open_parent_dir(output_path)


def _labeled_options(frame, label: str, row_num: int, options: list[str], default: str) -> tk.StringVar:
    _ = ttk.Label(frame, text=label)
    _.grid(row=row_num, column=0, sticky="E", padx=10, pady=10)

    _var = tk.StringVar(value=default)
    dropdown_menu = ttk.OptionMenu(frame, _var, default, *options)
    dropdown_menu.grid(row=row_num, column=1, sticky="W", padx=10, pady=10)
    return _var


def _file_handler(label: tk.StringVar, default: str) -> None:
    file_path = filedialog.askopenfilename()
    if file_path:
        label.set(file_path)
    else:
        label.set(default)


def _padded_placeholder(s: str) -> str:
    _pad = " " * int((100 - len(s)) / 2)
    return f"{_pad}<{s}>{_pad}"


def _file_selector(frame, placeholder: str, row_num: int) -> ttk.Label:
    _default = _padded_placeholder(placeholder)
    _var = tk.StringVar(value=_default)
    btn = ttk.Button(frame, textvariable=_var, command=lambda: _file_handler(_var, _default))
    btn.grid(row=row_num, columnspan=3)
    return _var


def add_core_widgets(main_frame) -> None:
    _row = 0
    ##### Input File Picker
    widgets_state["input_file"] = _file_selector(main_frame, "Input File", _row)
    _row += 1

    ##### Process Picker
    widgets_state["process"] = _labeled_options(
        main_frame, label="Process:", row_num=_row, options=cn.Process.options(), default=cn.DEFAULT_PROCESS
    )
    _row += 1

    ##### Image File Picker
    widgets_state["image_file"] = _file_selector(main_frame, "MP3 Icon", row_num=_row)
    _row += 1

    ##### Voice selection
    widgets_state["voice"] = _labeled_options(main_frame, "Voice:", _row, cn.VOICES, cn.DEFAULT_VOICE)
    _row += 1

    ##### Page Range
    _ = ttk.Label(main_frame, text="Page Range:")
    _.grid(row=_row, column=0, sticky="W", padx=10, pady=5)

    widgets_state["start_range"] = tk.StringVar(value=0)
    _ = ttk.Entry(main_frame, textvariable=widgets_state["start_range"], width=5)
    _.grid(row=_row, column=1, padx=2, pady=2)

    widgets_state["end_range"] = tk.StringVar(value=9999)
    _ = ttk.Entry(main_frame, textvariable=widgets_state["end_range"], width=5)
    _.grid(row=_row, column=2, padx=10, pady=5)
    _row += 1

    ##### Generate Button
    _ = ttk.Button(main_frame, text="Generate", command=_state_snapshot)
    _.grid(row=_row, column=0, columnspan=3, pady=30)
