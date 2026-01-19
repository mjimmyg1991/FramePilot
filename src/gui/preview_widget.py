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
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_start_crop: CropRegion | None = None

        # Display metrics
        self._display_scale = 1.0
        self._display_offset_x = 0
        self._display_offset_y = 0
        self._display_width = 0
        self._display_height = 0

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

        self._dim_label = ctk.CTkLabel(
            self._info_frame, text="",
            font=ctk.CTkFont(size=12), text_color="gray"
        )
        self._dim_label.pack(side="right")

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

    def _on_mouse_down(self, event):
        """Start dragging the crop or trigger file add when empty."""
        # If no image loaded, trigger file addition callback
        if self._current_image is None:
            if self._on_empty_click:
                self._on_empty_click()
            return

        if self._crop is None:
            return

        crop_left = self._display_offset_x + int(self._crop.left * self._display_width)
        crop_top = self._display_offset_y + int(self._crop.top * self._display_height)
        crop_right = self._display_offset_x + int(self._crop.right * self._display_width)
        crop_bottom = self._display_offset_y + int(self._crop.bottom * self._display_height)

        if crop_left <= event.x <= crop_right and crop_top <= event.y <= crop_bottom:
            self._dragging = True
            self._drag_start_x = event.x
            self._drag_start_y = event.y
            self._drag_start_crop = CropRegion(
                left=self._crop.left,
                right=self._crop.right,
                top=self._crop.top,
                bottom=self._crop.bottom,
            )
            self.canvas.config(cursor="fleur")

    def _on_mouse_drag(self, event):
        """Handle crop dragging."""
        if not self._dragging or self._drag_start_crop is None:
            return

        dx = (event.x - self._drag_start_x) / self._display_width
        dy = (event.y - self._drag_start_y) / self._display_height

        crop_width = self._drag_start_crop.width
        crop_height = self._drag_start_crop.height

        new_left = self._drag_start_crop.left + dx
        new_top = self._drag_start_crop.top + dy

        new_left = max(0, min(1 - crop_width, new_left))
        new_top = max(0, min(1 - crop_height, new_top))

        self._crop = CropRegion(
            left=new_left,
            right=new_left + crop_width,
            top=new_top,
            bottom=new_top + crop_height,
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
        scale = min(
            (canvas_width - 40) / img_width,
            (canvas_height - 40) / img_height,
        )
        scale = min(scale, 1.0)

        new_width = int(img_width * scale)
        new_height = int(img_height * scale)

        self._display_scale = scale
        self._display_width = new_width
        self._display_height = new_height
        self._display_offset_x = (canvas_width - new_width) // 2
        self._display_offset_y = (canvas_height - new_height) // 2

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
