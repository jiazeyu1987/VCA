from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from treatment_boundary_frame_delta import BoundaryDetectionError, analyze_folder


METHOD_TITLE = "Adjacent Frame Delta"
ANALYZE_MODULE_NAME = "treatment_boundary_frame_delta"
PREVIEW_SIZE = (460, 320)


def resolve_result_image_paths(folder: str | Path, payload: dict[str, object]) -> tuple[Path, Path]:
    folder_path = Path(folder)
    before_name = payload.get("before_frame")
    after_name = payload.get("after_frame")
    if not isinstance(before_name, str) or not before_name:
        raise BoundaryDetectionError("result missing before_frame")
    if not isinstance(after_name, str) or not after_name:
        raise BoundaryDetectionError("result missing after_frame")
    return folder_path / before_name, folder_path / after_name


class BoundaryGuiApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{METHOD_TITLE} Boundary Viewer")
        self.folder_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Choose a folder and calculate.")
        self.before_name_var = tk.StringVar(value="-")
        self.after_name_var = tk.StringVar(value="-")
        self.before_photo: ImageTk.PhotoImage | None = None
        self.after_photo: ImageTk.PhotoImage | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        top = ttk.Frame(self.root, padding=10)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Folder").grid(row=0, column=0, padx=(0, 8), sticky="w")
        ttk.Entry(top, textvariable=self.folder_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="Browse", command=self.choose_folder).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(top, text="Calculate", command=self.calculate).grid(row=0, column=3, padx=(8, 0))
        body = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)
        ttk.Label(body, text="Before frame").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="After frame").grid(row=0, column=1, sticky="w")
        self.before_image_label = ttk.Label(body, anchor="center")
        self.after_image_label = ttk.Label(body, anchor="center")
        self.before_image_label.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=8)
        self.after_image_label.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=8)
        ttk.Label(body, textvariable=self.before_name_var, wraplength=460).grid(row=2, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(body, textvariable=self.after_name_var, wraplength=460).grid(row=2, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 0, 10, 10)).grid(row=2, column=0, sticky="ew")

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title=f"Select folder for {METHOD_TITLE}")
        if selected:
            self.folder_var.set(selected)

    def calculate(self) -> None:
        folder_text = self.folder_var.get().strip()
        if not folder_text:
            messagebox.showerror("Missing folder", "Choose a folder before calculating.")
            return
        folder = Path(folder_text)
        try:
            payload = analyze_folder(folder)
            before_path, after_path = resolve_result_image_paths(folder, payload)
            self._show_result(before_path, after_path)
        except BoundaryDetectionError as exc:
            self.status_var.set("Calculation failed.")
            messagebox.showerror("Calculation failed", str(exc))
        except FileNotFoundError as exc:
            self.status_var.set("Image file missing.")
            messagebox.showerror("Image file missing", str(exc))

    def _show_result(self, before_path: Path, after_path: Path) -> None:
        if not before_path.is_file():
            raise FileNotFoundError(str(before_path))
        if not after_path.is_file():
            raise FileNotFoundError(str(after_path))
        self.before_photo = self._load_photo(before_path)
        self.after_photo = self._load_photo(after_path)
        self.before_image_label.configure(image=self.before_photo)
        self.after_image_label.configure(image=self.after_photo)
        self.before_name_var.set(before_path.name)
        self.after_name_var.set(after_path.name)
        self.status_var.set("Calculation completed.")

    def _load_photo(self, path: Path) -> ImageTk.PhotoImage:
        with Image.open(path) as image:
            preview = image.convert("RGB")
            preview.thumbnail(PREVIEW_SIZE)
            return ImageTk.PhotoImage(preview)


def main() -> None:
    root = tk.Tk()
    BoundaryGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
