"""Preview widget for displaying images with draggable crop overlay."""

import tkinter as tk
from pathlib import Path
from typing import Callable

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageTk

from ..crop_calculator import CropRegion
from ..detector import Detection


class PreviewWidget(ctk.CTkFrame):
    """Widget for displaying image previews with draggable crop overlay."""

    # Brand color for accent
    BRAND_ORANGE = "#FF6B35"

    def __init__(
        self,
        parent,
        on_crop_changed: Callable[[CropRegion], None] | None = None,
        on_empty_click: Callable[[], None] | None = None,
        **kwargs
    ):
        super().__init__(parent, fg_color="gray14", **kwargs)

        # Callback when user clicks empty preview (to add files)
        self._on_empty_click = on_empty_click

        self._current_image: Image.Image | None = None
        self._current_path: Path | None = None
        self._photo_image: ImageTk.PhotoImage | None = None
        self._crop: CropRegion | None = None
        self._detection: Detection | None = None
        self._aspect_ratio: tuple[int, int] = (4, 5)
        self._is_landscape: bool = False

        # Callback when user drags crop
        self._on_crop_changed = on_crop_changed

        # Drag state
        self._dragging = False
        self._drag_mode = "move"  # "move", "resize_tl", "resize_tr", "resize_bl", "resize_br", "resize_l", "resize_r", "resize_t", "resize_b"
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_start_crop: CropRegion | None = None
        self._edge_threshold = 15  # Pixels from edge to trigger resize

        # Display metrics
        self._display_scale = 1.0
        self._display_offset_x = 0
        self._display_offset_y = 0
        self._display_width = 0
        self._display_height = 0

        # Zoom state
        self._zoom_level = 1.0  # 1.0 = fit to window
        self._zoom_min = 0.25
        self._zoom_max = 5.0
        self._pan_x = 0.0  # Pan offset (normalized, 0 = centered)
        self._pan_y = 0.0
        self._fit_scale = 1.0  # Scale that fits image to window

        # Pan drag state
        self._panning = False
        self._pan_start_x = 0
        self._pan_start_y = 0

        self._setup_ui()

    def _setup_ui(self):
        """Set up the widget UI."""
        # Info bar at top
        self._info_frame = ctk.CTkFrame(self, fg_color="transparent", height=28)
        self._info_frame.pack(fill="x", padx=12, pady=(8, 4))

        self._ar_label = ctk.CTkLabel(
            self._info_frame, text="",
            font=ctk.CTkFont(size=12)
        )
        self._ar_label.pack(side="left")

        # Zoom controls (right side)
        zoom_frame = ctk.CTkFrame(self._info_frame, fg_color="transparent")
        zoom_frame.pack(side="right", padx=(8, 0))

        self._zoom_out_btn = ctk.CTkButton(
            zoom_frame, text="-", width=28, height=24,
            fg_color="#2a2a2e", hover_color="#3a3a3e",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._zoom_out
        )
        self._zoom_out_btn.pack(side="left", padx=1)

        self._zoom_label = ctk.CTkLabel(
            zoom_frame, text="Fit",
            font=ctk.CTkFont(size=11), width=50
        )
        self._zoom_label.pack(side="left", padx=2)

        self._zoom_in_btn = ctk.CTkButton(
            zoom_frame, text="+", width=28, height=24,
            fg_color="#2a2a2e", hover_color="#3a3a3e",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._zoom_in
        )
        self._zoom_in_btn.pack(side="left", padx=1)

        self._fit_btn = ctk.CTkButton(
            zoom_frame, text="Fit", width=38, height=24,
            fg_color="#2a2a2e", hover_color="#3a3a3e",
            font=ctk.CTkFont(size=11),
            command=self._zoom_fit
        )
        self._fit_btn.pack(side="left", padx=(8, 1))

        self._100_btn = ctk.CTkButton(
            zoom_frame, text="100%", width=45, height=24,
            fg_color="#2a2a2e", hover_color="#3a3a3e",
            font=ctk.CTkFont(size=11),
            command=self._zoom_100
        )
        self._100_btn.pack(side="left", padx=1)

        self._dim_label = ctk.CTkLabel(
            self._info_frame, text="",
            font=ctk.CTkFont(size=12), text_color="gray"
        )
        self._dim_label.pack(side="right", padx=(0, 12))

        # Canvas for image display
        self.canvas = tk.Canvas(
            self,
            bg="#1a1a1a",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # Empty state elements (more prominent)
        self._empty_state_ids = []

        # Bind events
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Motion>", self._on_mouse_move)

        # Zoom bindings
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)  # Windows
        self.canvas.bind("<Button-4>", self._on_mouse_wheel)    # Linux scroll up
        self.canvas.bind("<Button-5>", self._on_mouse_wheel)    # Linux scroll down

        # Pan bindings (middle mouse or Ctrl+left)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_motion)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_end)
        self.canvas.bind("<Control-ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<Control-B1-Motion>", self._on_pan_motion)
        self.canvas.bind("<Control-ButtonRelease-1>", self._on_pan_end)

    def _on_resize(self, event):
        """Handle canvas resize."""
        if self._current_image is not None:
            self._draw_preview()
        else:
            self._draw_empty_state()

    def _draw_empty_state(self):
        """Draw a prominent empty state with upload call-to-action."""
        # Clear any existing empty state elements
        for item_id in self._empty_state_ids:
            self.canvas.delete(item_id)
        self._empty_state_ids = []

        # Change cursor to hand pointer when empty (clickable)
        self.canvas.config(cursor="hand2")

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            return

        center_x = canvas_width // 2
        center_y = canvas_height // 2

        # Draw dashed border rectangle (drop zone indicator)
        padding = 40
        x1, y1 = padding, padding
        x2, y2 = canvas_width - padding, canvas_height - padding

        # Create dashed border effect with multiple rectangles
        dash_id = self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#3a3a3a",
            width=2,
            dash=(10, 6),
        )
        self._empty_state_ids.append(dash_id)

        # Upload icon (using unicode symbol)
        icon_id = self.canvas.create_text(
            center_x, center_y - 50,
            text="📁",
            font=("Segoe UI Emoji", 48),
            fill="#555555",
        )
        self._empty_state_ids.append(icon_id)

        # Main instruction text with brand color
        main_text_id = self.canvas.create_text(
            center_x, center_y + 20,
            text="Drop photos here to get started",
            font=("Segoe UI", 18, "bold"),
            fill=self.BRAND_ORANGE,
        )
        self._empty_state_ids.append(main_text_id)

        # Secondary instruction - make it clickable hint
        secondary_text_id = self.canvas.create_text(
            center_x, center_y + 55,
            text="Click here or use +Files / +Folder in sidebar",
            font=("Segoe UI", 12),
            fill="#888888",
        )
        self._empty_state_ids.append(secondary_text_id)

        # Supported formats hint
        formats_text_id = self.canvas.create_text(
            center_x, center_y + 85,
            text="Supports JPG, PNG, TIFF, RAW (CR2, CR3, NEF, ARW, DNG, RAF)",
            font=("Segoe UI", 10),
            fill="#555555",
        )
        self._empty_state_ids.append(formats_text_id)

    def _get_crop_bounds(self) -> tuple[int, int, int, int]:
        """Get crop bounds in screen coordinates."""
        if self._crop is None:
            return (0, 0, 0, 0)
        crop_left = self._display_offset_x + int(self._crop.left * self._display_width)
        crop_top = self._display_offset_y + int(self._crop.top * self._display_height)
        crop_right = self._display_offset_x + int(self._crop.right * self._display_width)
        crop_bottom = self._display_offset_y + int(self._crop.bottom * self._display_height)
        return (crop_left, crop_top, crop_right, crop_bottom)

    def _get_drag_mode(self, x: int, y: int) -> str:
        """Determine what kind of drag operation based on mouse position."""
        if self._crop is None:
            return ""

        crop_left, crop_top, crop_right, crop_bottom = self._get_crop_bounds()
        t = self._edge_threshold

        # Check if outside crop entirely
        if x < crop_left - t or x > crop_right + t or y < crop_top - t or y > crop_bottom + t:
            return ""

        # Check corners first (priority over edges)
        near_left = abs(x - crop_left) < t
        near_right = abs(x - crop_right) < t
        near_top = abs(y - crop_top) < t
        near_bottom = abs(y - crop_bottom) < t

        if near_top and near_left:
            return "resize_tl"
        if near_top and near_right:
            return "resize_tr"
        if near_bottom and near_left:
            return "resize_bl"
        if near_bottom and near_right:
            return "resize_br"

        # Check edges
        if near_left and crop_top < y < crop_bottom:
            return "resize_l"
        if near_right and crop_top < y < crop_bottom:
            return "resize_r"
        if near_top and crop_left < x < crop_right:
            return "resize_t"
        if near_bottom and crop_left < x < crop_right:
            return "resize_b"

        # Inside crop area = move
        if crop_left <= x <= crop_right and crop_top <= y <= crop_bottom:
            return "move"

        return ""

    def _get_cursor_for_mode(self, mode: str) -> str:
        """Get cursor style for drag mode."""
        cursors = {
            "move": "fleur",
            "resize_tl": "top_left_corner",
            "resize_tr": "top_right_corner",
            "resize_bl": "bottom_left_corner",
            "resize_br": "bottom_right_corner",
            "resize_l": "sb_h_double_arrow",
            "resize_r": "sb_h_double_arrow",
            "resize_t": "sb_v_double_arrow",
            "resize_b": "sb_v_double_arrow",
        }
        return cursors.get(mode, "crosshair")

    def _on_mouse_move(self, event):
        """Update cursor based on mouse position over crop edges."""
        if self._current_image is None or self._crop is None or self._dragging:
            return

        mode = self._get_drag_mode(event.x, event.y)
        cursor = self._get_cursor_for_mode(mode) if mode else "crosshair"
        self.canvas.config(cursor=cursor)

    def _on_mouse_down(self, event):
        """Start dragging the crop or trigger file add when empty."""
        # If no image loaded, trigger file addition callback
        if self._current_image is None:
            if self._on_empty_click:
                self._on_empty_click()
            return

        if self._crop is None:
            return

        mode = self._get_drag_mode(event.x, event.y)
        if mode:
            self._dragging = True
            self._drag_mode = mode
            self._drag_start_x = event.x
            self._drag_start_y = event.y
            self._drag_start_crop = CropRegion(
                left=self._crop.left,
                right=self._crop.right,
                top=self._crop.top,
                bottom=self._crop.bottom,
            )
            self.canvas.config(cursor=self._get_cursor_for_mode(mode))

    def _on_mouse_drag(self, event):
        """Handle crop dragging or resizing."""
        if not self._dragging or self._drag_start_crop is None:
            return

        dx = (event.x - self._drag_start_x) / self._display_width
        dy = (event.y - self._drag_start_y) / self._display_height

        start = self._drag_start_crop
        aspect_ratio = start.width / start.height if start.height > 0 else 1.0

        if self._drag_mode == "move":
            # Move crop while maintaining size
            crop_width = start.width
            crop_height = start.height
            new_left = max(0, min(1 - crop_width, start.left + dx))
            new_top = max(0, min(1 - crop_height, start.top + dy))
            self._crop = CropRegion(
                left=new_left,
                right=new_left + crop_width,
                top=new_top,
                bottom=new_top + crop_height,
            )
        else:
            # Resize while maintaining aspect ratio
            new_left = start.left
            new_right = start.right
            new_top = start.top
            new_bottom = start.bottom

            if self._drag_mode in ("resize_br", "resize_r", "resize_b"):
                # Resize from bottom-right: anchor top-left
                if self._drag_mode == "resize_r":
                    new_right = max(new_left + 0.05, min(1.0, start.right + dx))
                    new_width = new_right - new_left
                    new_height = new_width / aspect_ratio
                    new_bottom = new_top + new_height
                elif self._drag_mode == "resize_b":
                    new_bottom = max(new_top + 0.05, min(1.0, start.bottom + dy))
                    new_height = new_bottom - new_top
                    new_width = new_height * aspect_ratio
                    new_right = new_left + new_width
                else:  # resize_br
                    # Use the larger movement to determine resize
                    if abs(dx) > abs(dy):
                        new_right = max(new_left + 0.05, min(1.0, start.right + dx))
                        new_width = new_right - new_left
                        new_height = new_width / aspect_ratio
                        new_bottom = new_top + new_height
                    else:
                        new_bottom = max(new_top + 0.05, min(1.0, start.bottom + dy))
                        new_height = new_bottom - new_top
                        new_width = new_height * aspect_ratio
                        new_right = new_left + new_width

            elif self._drag_mode in ("resize_tl", "resize_l", "resize_t"):
                # Resize from top-left: anchor bottom-right
                if self._drag_mode == "resize_l":
                    new_left = max(0, min(new_right - 0.05, start.left + dx))
                    new_width = new_right - new_left
                    new_height = new_width / aspect_ratio
                    new_top = new_bottom - new_height
                elif self._drag_mode == "resize_t":
                    new_top = max(0, min(new_bottom - 0.05, start.top + dy))
                    new_height = new_bottom - new_top
                    new_width = new_height * aspect_ratio
                    new_left = new_right - new_width
                else:  # resize_tl
                    if abs(dx) > abs(dy):
                        new_left = max(0, min(new_right - 0.05, start.left + dx))
                        new_width = new_right - new_left
                        new_height = new_width / aspect_ratio
                        new_top = new_bottom - new_height
                    else:
                        new_top = max(0, min(new_bottom - 0.05, start.top + dy))
                        new_height = new_bottom - new_top
                        new_width = new_height * aspect_ratio
                        new_left = new_right - new_width

            elif self._drag_mode == "resize_tr":
                # Resize from top-right: anchor bottom-left
                if abs(dx) > abs(dy):
                    new_right = max(new_left + 0.05, min(1.0, start.right + dx))
                    new_width = new_right - new_left
                    new_height = new_width / aspect_ratio
                    new_top = new_bottom - new_height
                else:
                    new_top = max(0, min(new_bottom - 0.05, start.top + dy))
                    new_height = new_bottom - new_top
                    new_width = new_height * aspect_ratio
                    new_right = new_left + new_width

            elif self._drag_mode == "resize_bl":
                # Resize from bottom-left: anchor top-right
                if abs(dx) > abs(dy):
                    new_left = max(0, min(new_right - 0.05, start.left + dx))
                    new_width = new_right - new_left
                    new_height = new_width / aspect_ratio
                    new_bottom = new_top + new_height
                else:
                    new_bottom = max(new_top + 0.05, min(1.0, start.bottom + dy))
                    new_height = new_bottom - new_top
                    new_width = new_height * aspect_ratio
                    new_left = new_right - new_width

            # Clamp to image bounds
            if new_left < 0:
                new_left = 0
                new_width = new_right - new_left
                new_height = new_width / aspect_ratio
                if self._drag_mode in ("resize_tl", "resize_t", "resize_l"):
                    new_top = new_bottom - new_height
                else:
                    new_bottom = new_top + new_height

            if new_right > 1.0:
                new_right = 1.0
                new_width = new_right - new_left
                new_height = new_width / aspect_ratio
                if self._drag_mode in ("resize_tr", "resize_t", "resize_r"):
                    new_top = new_bottom - new_height
                else:
                    new_bottom = new_top + new_height

            if new_top < 0:
                new_top = 0
                new_height = new_bottom - new_top
                new_width = new_height * aspect_ratio
                if self._drag_mode in ("resize_tl", "resize_l", "resize_t"):
                    new_left = new_right - new_width
                else:
                    new_right = new_left + new_width

            if new_bottom > 1.0:
                new_bottom = 1.0
                new_height = new_bottom - new_top
                new_width = new_height * aspect_ratio
                if self._drag_mode in ("resize_bl", "resize_l", "resize_b"):
                    new_left = new_right - new_width
                else:
                    new_right = new_left + new_width

            self._crop = CropRegion(
                left=max(0, new_left),
                right=min(1.0, new_right),
                top=max(0, new_top),
                bottom=min(1.0, new_bottom),
            )

        self._draw_preview()
        self._update_info_labels()

    def _on_mouse_up(self, event):
        """End dragging."""
        if self._dragging:
            self._dragging = False
            self.canvas.config(cursor="crosshair")

            if self._on_crop_changed and self._crop:
                self._on_crop_changed(self._crop)

    # Zoom methods
    def _zoom_in(self):
        """Zoom in by 25%."""
        self._set_zoom(self._zoom_level * 1.25)

    def _zoom_out(self):
        """Zoom out by 20%."""
        self._set_zoom(self._zoom_level * 0.8)

    def _zoom_fit(self):
        """Reset zoom to fit window."""
        self._zoom_level = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._update_zoom_label()
        self._draw_preview()

    def _zoom_100(self):
        """Set zoom to actual pixels (100%)."""
        if self._current_image is None or self._fit_scale == 0:
            return
        self._zoom_level = 1.0 / self._fit_scale
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._update_zoom_label()
        self._draw_preview()

    def _set_zoom(self, level: float, center_x: int | None = None, center_y: int | None = None):
        """Set zoom level, optionally centered on a point."""
        old_zoom = self._zoom_level
        self._zoom_level = max(self._zoom_min, min(self._zoom_max, level))

        # Adjust pan to keep the center point stationary when zooming with mouse
        if center_x is not None and center_y is not None and self._display_width > 0:
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()

            # Convert screen point to normalized image coordinates
            rel_x = (center_x - canvas_width / 2) / (self._display_width * old_zoom) if self._display_width else 0
            rel_y = (center_y - canvas_height / 2) / (self._display_height * old_zoom) if self._display_height else 0

            # Adjust pan so the same image point stays under the cursor
            zoom_ratio = self._zoom_level / old_zoom
            self._pan_x = self._pan_x + rel_x * (1 - zoom_ratio)
            self._pan_y = self._pan_y + rel_y * (1 - zoom_ratio)

        self._clamp_pan()
        self._update_zoom_label()
        self._draw_preview()

    def _clamp_pan(self):
        """Clamp pan values to prevent scrolling past image edges."""
        max_pan = max(0, (self._zoom_level - 1) / (2 * self._zoom_level)) if self._zoom_level > 0 else 0
        self._pan_x = max(-max_pan, min(max_pan, self._pan_x))
        self._pan_y = max(-max_pan, min(max_pan, self._pan_y))

    def _update_zoom_label(self):
        """Update zoom level display."""
        if abs(self._zoom_level - 1.0) < 0.01:
            self._zoom_label.configure(text="Fit")
        else:
            actual_zoom = self._zoom_level * self._fit_scale * 100
            self._zoom_label.configure(text=f"{actual_zoom:.0f}%")

    def _on_mouse_wheel(self, event):
        """Handle mouse wheel zoom."""
        if self._current_image is None:
            return

        # Determine scroll direction
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            factor = 1.15
        else:
            factor = 0.87

        self._set_zoom(self._zoom_level * factor, event.x, event.y)

    def _on_pan_start(self, event):
        """Start panning."""
        if self._current_image is None:
            return
        self._panning = True
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self.canvas.config(cursor="fleur")

    def _on_pan_motion(self, event):
        """Handle pan dragging."""
        if not self._panning or self._display_width == 0:
            return

        dx = (event.x - self._pan_start_x) / (self._display_width * self._zoom_level)
        dy = (event.y - self._pan_start_y) / (self._display_height * self._zoom_level)

        self._pan_x -= dx
        self._pan_y -= dy
        self._clamp_pan()

        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self._draw_preview()

    def _on_pan_end(self, event):
        """End panning."""
        if self._panning:
            self._panning = False
            self.canvas.config(cursor="crosshair")

    def set_aspect_ratio(self, aspect: tuple[int, int], is_landscape: bool = False):
        """Set the aspect ratio for display info."""
        self._aspect_ratio = aspect
        self._is_landscape = is_landscape
        self._update_info_labels()

    def _update_info_labels(self):
        """Update the info labels."""
        if self._crop is None or self._current_image is None:
            self._ar_label.configure(text="")
            self._dim_label.configure(text="")
            return

        w, h = self._aspect_ratio
        if self._is_landscape:
            ar_text = f"Aspect: {h}:{w} (landscape)"
        else:
            ar_text = f"Aspect: {w}:{h} (portrait)"
        self._ar_label.configure(text=ar_text)

        img_w, img_h = self._current_image.size
        crop_w = int(self._crop.width * img_w)
        crop_h = int(self._crop.height * img_h)
        self._dim_label.configure(text=f"Crop: {crop_w} × {crop_h}px")

    def clear(self):
        """Clear the preview."""
        self._current_image = None
        self._current_path = None
        self._photo_image = None
        self._crop = None
        self._detection = None
        self.canvas.delete("preview")
        self._ar_label.configure(text="")
        self._dim_label.configure(text="")
        # Redraw empty state
        self._draw_empty_state()

    def load_image(
        self,
        image_path: Path,
        crop: CropRegion | None = None,
        detection: Detection | None = None,
    ):
        """Load and display an image with optional crop overlay."""
        try:
            self._current_image = Image.open(image_path)
            self._current_path = image_path
            self._crop = crop
            self._detection = detection

            # Reset zoom/pan for new image
            self._zoom_level = 1.0
            self._pan_x = 0.0
            self._pan_y = 0.0
            self._update_zoom_label()

            # Clear empty state elements
            for item_id in self._empty_state_ids:
                self.canvas.delete(item_id)
            self._empty_state_ids = []
            # Restore crosshair cursor for image interaction
            self.canvas.config(cursor="crosshair")
            self._draw_preview()
            self._update_info_labels()
        except Exception as e:
            self.clear()
            # Show error on canvas
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            error_id = self.canvas.create_text(
                canvas_width // 2, canvas_height // 2,
                text=f"Error loading image:\n{e}",
                fill="#EF4444",
                font=("Segoe UI", 12),
            )
            self._empty_state_ids.append(error_id)

    def update_crop(self, crop: CropRegion | None, detection: Detection | None = None):
        """Update the crop overlay without reloading the image."""
        self._crop = crop
        self._detection = detection
        if self._current_image is not None:
            self._draw_preview()
            self._update_info_labels()

    def get_crop(self) -> CropRegion | None:
        """Get the current crop region."""
        return self._crop

    def _draw_preview(self):
        """Draw the image with crop overlay on canvas."""
        if self._current_image is None:
            return

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            return

        img_width, img_height = self._current_image.size

        # Calculate fit scale (base scale that fits image to window)
        self._fit_scale = min(
            (canvas_width - 40) / img_width,
            (canvas_height - 40) / img_height,
        )
        self._fit_scale = min(self._fit_scale, 1.0)

        # Apply zoom to get actual display scale
        scale = self._fit_scale * self._zoom_level

        new_width = int(img_width * scale)
        new_height = int(img_height * scale)

        self._display_scale = scale
        self._display_width = new_width
        self._display_height = new_height

        # Calculate display position with pan offset
        base_offset_x = (canvas_width - new_width) // 2
        base_offset_y = (canvas_height - new_height) // 2
        self._display_offset_x = int(base_offset_x - self._pan_x * new_width)
        self._display_offset_y = int(base_offset_y - self._pan_y * new_height)

        resized = self._current_image.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS,
        )

        overlay = resized.copy().convert("RGBA")
        draw = ImageDraw.Draw(overlay)

        if self._crop is not None:
            crop_left = int(self._crop.left * new_width)
            crop_top = int(self._crop.top * new_height)
            crop_right = int(self._crop.right * new_width)
            crop_bottom = int(self._crop.bottom * new_height)

            # Darken areas outside crop
            dark_overlay = Image.new("RGBA", overlay.size, (0, 0, 0, 0))
            dark_draw = ImageDraw.Draw(dark_overlay)

            if crop_top > 0:
                dark_draw.rectangle([0, 0, new_width, crop_top], fill=(0, 0, 0, 160))
            if crop_bottom < new_height:
                dark_draw.rectangle([0, crop_bottom, new_width, new_height], fill=(0, 0, 0, 160))
            if crop_left > 0:
                dark_draw.rectangle([0, crop_top, crop_left, crop_bottom], fill=(0, 0, 0, 160))
            if crop_right < new_width:
                dark_draw.rectangle([crop_right, crop_top, new_width, crop_bottom], fill=(0, 0, 0, 160))

            overlay = Image.alpha_composite(overlay, dark_overlay)
            draw = ImageDraw.Draw(overlay)

            # Draw crop border with glow effect
            for offset in range(3, 0, -1):
                alpha = 40 + (3 - offset) * 30
                draw.rectangle(
                    [crop_left - offset, crop_top - offset,
                     crop_right + offset, crop_bottom + offset],
                    outline=(0, 120, 212, alpha),
                    width=1,
                )

            # Main border
            draw.rectangle(
                [crop_left, crop_top, crop_right, crop_bottom],
                outline=(0, 150, 255),
                width=2,
            )

            # Corner handles
            handle_size = 10
            handle_color = (255, 255, 255)
            corners = [
                (crop_left, crop_top),
                (crop_right, crop_top),
                (crop_left, crop_bottom),
                (crop_right, crop_bottom),
            ]
            for hx, hy in corners:
                draw.rectangle(
                    [hx - handle_size//2, hy - handle_size//2,
                     hx + handle_size//2, hy + handle_size//2],
                    fill=handle_color,
                    outline=(0, 150, 255),
                    width=2,
                )

            # Aspect ratio text in center
            ar_w, ar_h = self._aspect_ratio
            if self._is_landscape:
                ar_text = f"{ar_h}:{ar_w}"
            else:
                ar_text = f"{ar_w}:{ar_h}"

            text_x = (crop_left + crop_right) // 2
            text_y = (crop_top + crop_bottom) // 2

            try:
                font = ImageFont.truetype("segoeui.ttf", 18)
            except:
                try:
                    font = ImageFont.truetype("arial.ttf", 18)
                except:
                    font = ImageFont.load_default()

            bbox = draw.textbbox((text_x, text_y), ar_text, font=font, anchor="mm")
            padding = 8
            draw.rounded_rectangle(
                [bbox[0] - padding, bbox[1] - padding,
                 bbox[2] + padding, bbox[3] + padding],
                radius=6,
                fill=(0, 0, 0, 200),
            )
            draw.text((text_x, text_y), ar_text, fill=(255, 255, 255), font=font, anchor="mm")

            # Drag hint
            if crop_bottom - crop_top > 80:
                hint_y = crop_bottom - 25
                try:
                    hint_font = ImageFont.truetype("segoeui.ttf", 11)
                except:
                    hint_font = font
                draw.text(
                    ((crop_left + crop_right) // 2, hint_y),
                    "drag to reposition",
                    fill=(180, 180, 180),
                    font=hint_font,
                    anchor="mm",
                )

        if self._detection is not None:
            det_left = int(self._detection.bbox[0] * new_width)
            det_top = int(self._detection.bbox[1] * new_height)
            det_right = int(self._detection.bbox[2] * new_width)
            det_bottom = int(self._detection.bbox[3] * new_height)

            # Detection box with glow
            for offset in range(2, 0, -1):
                alpha = 60 + (2 - offset) * 40
                draw.rectangle(
                    [det_left - offset, det_top - offset,
                     det_right + offset, det_bottom + offset],
                    outline=(78, 201, 176, alpha),
                    width=1,
                )

            draw.rectangle(
                [det_left, det_top, det_right, det_bottom],
                outline=(78, 201, 176),
                width=2,
            )

            # Label with background
            label = f"{self._detection.label} {self._detection.confidence:.0%}"
            try:
                label_font = ImageFont.truetype("segoeui.ttf", 12)
            except:
                label_font = font if 'font' in dir() else ImageFont.load_default()

            label_bbox = draw.textbbox((det_left, det_top - 20), label, font=label_font)
            draw.rectangle(
                [label_bbox[0] - 4, label_bbox[1] - 2,
                 label_bbox[2] + 4, label_bbox[3] + 2],
                fill=(78, 201, 176),
            )
            draw.text((det_left, det_top - 20), label, fill=(0, 0, 0), font=label_font)

        self._photo_image = ImageTk.PhotoImage(overlay)

        self.canvas.delete("preview")
        self.canvas.create_image(
            canvas_width // 2,
            canvas_height // 2,
            image=self._photo_image,
            anchor=tk.CENTER,
            tags="preview",
        )
