"""XMP sidecar file handler for Lightroom crop data."""

import shutil
from pathlib import Path

from lxml import etree

from .crop_calculator import CropRegion


# XML namespaces used in XMP files
NAMESPACES = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
}

# XMP template for new sidecar files
XMP_TEMPLATE = """<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Lightroom Subject Crop">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about=""
      xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
      crs:Version="15.0"
      crs:ProcessVersion="11.0"
      crs:HasCrop="True"
      crs:CropTop="{crop_top}"
      crs:CropLeft="{crop_left}"
      crs:CropBottom="{crop_bottom}"
      crs:CropRight="{crop_right}"
      crs:CropAngle="0"
      crs:CropConstrainToWarp="0">
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def get_xmp_path(image_path: str | Path) -> Path:
    """Get the XMP sidecar path for an image.

    Args:
        image_path: Path to the image file

    Returns:
        Path to the XMP sidecar file (same name with .xmp extension)
    """
    image_path = Path(image_path)
    return image_path.with_suffix(image_path.suffix + ".xmp")


def read_xmp(xmp_path: str | Path) -> etree._Element | None:
    """Read and parse an XMP sidecar file.

    Args:
        xmp_path: Path to the XMP file

    Returns:
        Parsed XML element tree or None if file doesn't exist
    """
    xmp_path = Path(xmp_path)
    if not xmp_path.exists():
        return None

    with open(xmp_path, "rb") as f:
        content = f.read()

    # Parse the XMP content
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.fromstring(content, parser)


def create_xmp_from_template(crop: CropRegion) -> str:
    """Create a new XMP file content from template.

    Args:
        crop: CropRegion with crop coordinates

    Returns:
        XMP file content as string
    """
    return XMP_TEMPLATE.format(
        crop_top=f"{crop.top:.6f}",
        crop_left=f"{crop.left:.6f}",
        crop_bottom=f"{crop.bottom:.6f}",
        crop_right=f"{crop.right:.6f}"
    )


def update_xmp_crop(root: etree._Element, crop: CropRegion) -> etree._Element:
    """Update crop values in an existing XMP tree.

    Args:
        root: Parsed XMP root element
        crop: CropRegion with new crop coordinates

    Returns:
        Updated XML element tree
    """
    # Find the rdf:Description element with crs namespace attributes
    descriptions = root.xpath(
        "//rdf:Description",
        namespaces=NAMESPACES
    )

    if not descriptions:
        raise ValueError("No rdf:Description element found in XMP")

    # Find or create the description with Camera Raw settings
    crs_desc = None
    for desc in descriptions:
        # Check if this description has any crs attributes
        for attr in desc.attrib:
            if attr.startswith("{" + NAMESPACES["crs"] + "}"):
                crs_desc = desc
                break
        if crs_desc is not None:
            break

    if crs_desc is None:
        # Use the first description and add crs namespace
        crs_desc = descriptions[0]
        # Register the crs namespace
        etree.register_namespace("crs", NAMESPACES["crs"])

    # Update crop attributes
    crs_ns = "{" + NAMESPACES["crs"] + "}"

    crs_desc.set(crs_ns + "HasCrop", "True")
    crs_desc.set(crs_ns + "CropTop", f"{crop.top:.6f}")
    crs_desc.set(crs_ns + "CropLeft", f"{crop.left:.6f}")
    crs_desc.set(crs_ns + "CropBottom", f"{crop.bottom:.6f}")
    crs_desc.set(crs_ns + "CropRight", f"{crop.right:.6f}")
    crs_desc.set(crs_ns + "CropAngle", "0")

    return root


def write_crop_to_xmp(
    image_path: str | Path,
    crop: CropRegion,
    output_dir: str | Path | None = None,
    backup: bool = True
) -> Path:
    """Write crop data to an XMP sidecar file.

    If an XMP file already exists, it will be updated with new crop values
    while preserving other metadata. Otherwise, a new XMP file is created.

    Args:
        image_path: Path to the image file
        crop: CropRegion with crop coordinates
        output_dir: Optional output directory (default: same as image)
        backup: Whether to create backup of existing XMP files

    Returns:
        Path to the written XMP file
    """
    image_path = Path(image_path)

    # Determine output XMP path
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        xmp_filename = image_path.stem + image_path.suffix + ".xmp"
        xmp_path = output_dir / xmp_filename
    else:
        xmp_path = get_xmp_path(image_path)

    # Check for existing XMP file (in original location)
    existing_xmp_path = get_xmp_path(image_path)
    existing_xmp = None
    if existing_xmp_path.exists():
        existing_xmp = read_xmp(existing_xmp_path)

        # Create backup if requested
        if backup:
            backup_path = existing_xmp_path.with_suffix(".xmp.bak")
            shutil.copy2(existing_xmp_path, backup_path)

    # Generate XMP content
    if existing_xmp is not None:
        # Update existing XMP
        updated_xmp = update_xmp_crop(existing_xmp, crop)
        xmp_content = etree.tostring(
            updated_xmp,
            xml_declaration=True,
            encoding="UTF-8",
            pretty_print=True
        ).decode("utf-8")

        # Add xpacket wrapper if not present
        if "<?xpacket" not in xmp_content:
            xmp_content = (
                '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
                + xmp_content
                + '\n<?xpacket end="w"?>'
            )
    else:
        # Create new XMP from template
        xmp_content = create_xmp_from_template(crop)

    # Write XMP file
    with open(xmp_path, "w", encoding="utf-8") as f:
        f.write(xmp_content)

    return xmp_path


def read_crop_from_xmp(xmp_path: str | Path) -> CropRegion | None:
    """Read existing crop data from an XMP file.

    Args:
        xmp_path: Path to the XMP file

    Returns:
        CropRegion if crop data exists, None otherwise
    """
    root = read_xmp(xmp_path)
    if root is None:
        return None

    # Find crop attributes
    descriptions = root.xpath(
        "//rdf:Description",
        namespaces=NAMESPACES
    )

    crs_ns = "{" + NAMESPACES["crs"] + "}"

    for desc in descriptions:
        has_crop = desc.get(crs_ns + "HasCrop")
        if has_crop != "True":
            continue

        try:
            crop_left = float(desc.get(crs_ns + "CropLeft", "0"))
            crop_right = float(desc.get(crs_ns + "CropRight", "1"))
            crop_top = float(desc.get(crs_ns + "CropTop", "0"))
            crop_bottom = float(desc.get(crs_ns + "CropBottom", "1"))

            return CropRegion(
                left=crop_left,
                right=crop_right,
                top=crop_top,
                bottom=crop_bottom
            )
        except (ValueError, TypeError):
            continue

    return None
