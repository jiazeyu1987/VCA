from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

import tools.image_annotation_exporter as exporter


def write_image(path: Path, color: tuple[int, int, int] = (0, 0, 0)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 60), color).save(path)


def make_image_bytes(color: tuple[int, int, int] = (0, 0, 0)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(buffer, format="PNG")
    return buffer.getvalue()


def write_session_zip(path: Path, session_id: str = "20260625_113655_096_point_112781_15134606") -> None:
    manifest = {
        "session_id": session_id,
        "point_id": 112781,
        "frame_count": 2,
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("events.jsonl", "")
        zf.writestr("frames/frame_000002_seq_000066000_offline_capture.png", make_image_bytes((20, 0, 0)))
        zf.writestr("frames/frame_000001_seq_000065999_offline_capture.png", make_image_bytes((0, 20, 0)))
        zf.writestr("results/offline_result.json", "{}")


class ImageAnnotationExporterTests(unittest.TestCase):
    def test_packaging_scripts_target_standalone_image_annotation_exporter_exe(self):
        root = Path(__file__).resolve().parents[1]
        batch_path = root / "package_image_annotation_exporter.bat"
        ps1_path = root / "tools" / "package_image_annotation_exporter.ps1"

        self.assertTrue(batch_path.is_file())
        self.assertTrue(ps1_path.is_file())
        self.assertIn("package_image_annotation_exporter.ps1", batch_path.read_text(encoding="utf-8"))
        script_text = ps1_path.read_text(encoding="utf-8")
        self.assertIn("tools\\image_annotation_exporter.py", script_text)
        self.assertIn("image_annotation_exporter", script_text)
        self.assertIn("--onefile", script_text)

    def test_discover_images_filters_supported_extensions_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_image(root / "b.jpg")
            write_image(root / "a.png")
            (root / "notes.txt").write_text("not an image", encoding="utf-8")

            paths = exporter.discover_images(root)

            self.assertEqual([path.name for path in paths], ["a.png", "b.jpg"])

    def test_render_annotations_draws_cross_and_rectangle_without_mutating_original(self):
        image = Image.new("RGB", (80, 60), (0, 0, 0))
        original_bytes = image.tobytes()
        annotations = [
            exporter.Annotation(kind="cross", coords=(20, 10), label="A"),
            exporter.Annotation(kind="rectangle", coords=(30, 20, 60, 45), label="B"),
        ]

        rendered = exporter.render_annotations(image, annotations)

        self.assertEqual(image.tobytes(), original_bytes)
        self.assertNotEqual(rendered.tobytes(), original_bytes)
        self.assertNotEqual(rendered.getpixel((20, 10)), (0, 0, 0))
        self.assertNotEqual(rendered.getpixel((30, 20)), (0, 0, 0))

    def test_render_annotations_draws_brush_path_without_mutating_original(self):
        image = Image.new("RGB", (80, 60), (0, 0, 0))
        original_bytes = image.tobytes()

        rendered = exporter.render_annotations(
            image,
            [exporter.Annotation(kind="brush", coords=(5, 5, 20, 5, 20, 25), width=5)],
        )

        self.assertEqual(image.tobytes(), original_bytes)
        self.assertNotEqual(rendered.tobytes(), original_bytes)
        self.assertNotEqual(rendered.getpixel((15, 5)), (0, 0, 0))
        self.assertNotEqual(rendered.getpixel((20, 20)), (0, 0, 0))

    def test_preview_layout_upscales_image_to_fill_available_canvas_edge(self):
        layout = exporter.calculate_preview_layout((600, 512), (1200, 900))

        self.assertGreater(layout.width, 600)
        self.assertGreater(layout.height, 512)
        self.assertTrue(layout.width == 1200 or layout.height == 900)
        self.assertGreater(layout.scale, 1.0)

    def test_export_annotated_images_writes_originals_and_masks_with_matching_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            output_dir = root / "out"
            first = source_dir / "frame_001.png"
            second = source_dir / "frame_002.png"
            write_image(first, (10, 20, 30))
            write_image(second, (40, 50, 60))
            records = [
                exporter.ImageAnnotationRecord(first, [exporter.Annotation(kind="cross", coords=(10, 10))]),
                exporter.ImageAnnotationRecord(second, [exporter.Annotation(kind="rectangle", coords=(5, 5, 30, 25))]),
            ]

            rows = exporter.export_annotated_images(records, output_dir)

            self.assertEqual([row.original_name for row in rows], ["frame_001.png", "frame_002.png"])
            self.assertEqual([row.export_name for row in rows], ["frame_001.png", "frame_002.png"])
            self.assertEqual(sorted(path.name for path in output_dir.iterdir()), ["masks", "original_images"])
            original_files = sorted(path.name for path in (output_dir / "original_images").iterdir())
            mask_files = sorted(path.name for path in (output_dir / "masks").iterdir())
            self.assertEqual(original_files, ["frame_001.png", "frame_002.png"])
            self.assertEqual(mask_files, original_files)
            for row in rows:
                self.assertTrue(row.original_export_path.is_file())
                self.assertTrue(row.mask_path.is_file())
            with Image.open(output_dir / "original_images" / "frame_001.png") as original:
                self.assertEqual(original.getpixel((0, 0)), (10, 20, 30))
            with Image.open(output_dir / "masks" / "frame_001.png") as mask:
                self.assertEqual(mask.mode, "L")
                self.assertEqual(mask.size, (80, 60))
                self.assertGreater(mask.getpixel((10, 10)), 0)
                self.assertEqual(mask.getpixel((70, 50)), 0)

    def test_export_annotated_images_fails_when_no_annotations_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "source.png"
            write_image(image_path)

            with self.assertRaisesRegex(ValueError, "no annotated images"):
                exporter.export_annotated_images([exporter.ImageAnnotationRecord(image_path, [])], root / "out")

    def test_export_annotated_images_fails_when_output_has_unexpected_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_path = root / "source.png"
            output_dir = root / "out"
            output_dir.mkdir()
            (output_dir / "mapping.csv").write_text("old export", encoding="utf-8")
            write_image(image_path)

            with self.assertRaisesRegex(ValueError, "export directory must be empty"):
                exporter.export_annotated_images(
                    [exporter.ImageAnnotationRecord(image_path, [exporter.Annotation(kind="cross", coords=(10, 10))])],
                    output_dir,
                )

    def test_discover_session_zips_filters_session_archives_and_sorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_session_zip(root / "session_b.zip", "session_b")
            write_session_zip(root / "session_a.zip", "session_a")
            write_session_zip(root / "other.zip", "other")
            (root / "session_note.txt").write_text("not a zip", encoding="utf-8")

            paths = exporter.discover_session_zips(root)

            self.assertEqual([path.name for path in paths], ["session_a.zip", "session_b.zip"])

    def test_load_session_zip_images_reads_frame_members_and_manifest_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "session_20260625_113655_096_point_112781_15134606.zip"
            write_session_zip(zip_path)

            records = exporter.load_session_zip_images(zip_path)

            self.assertEqual(
                [record.member_name for record in records],
                [
                    "frames/frame_000001_seq_000065999_offline_capture.png",
                    "frames/frame_000002_seq_000066000_offline_capture.png",
                ],
            )
            self.assertEqual(records[0].session_zip_path, zip_path)
            self.assertEqual(records[0].session_id, "20260625_113655_096_point_112781_15134606")
            self.assertEqual(records[0].point_id, "112781")
            with records[0].open_image() as image:
                self.assertEqual(image.size, (80, 60))

    def test_load_session_zip_images_fails_fast_without_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "session_empty.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("manifest.json", json.dumps({"session_id": "session_empty"}))

            with self.assertRaisesRegex(ValueError, "no frame images found"):
                exporter.load_session_zip_images(zip_path)

    def test_export_session_zip_annotations_preserves_zip_frame_names_in_two_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            zip_path = root / "session_20260625_113655_096_point_112781_15134606.zip"
            output_dir = root / "out"
            write_session_zip(zip_path)
            records = exporter.load_session_zip_images(zip_path)
            records[0].annotations.append(exporter.Annotation(kind="cross", coords=(10, 10)))

            rows = exporter.export_annotated_images(records, output_dir)

            self.assertEqual(len(rows), 1)
            self.assertEqual(
                rows[0].export_name,
                "session_20260625_113655_096_point_112781_15134606__frame_000001_seq_000065999_offline_capture.png",
            )
            self.assertTrue(rows[0].original_export_path.is_file())
            self.assertTrue(rows[0].mask_path.is_file())
            self.assertEqual(rows[0].session_zip, zip_path.name)
            self.assertEqual(rows[0].session_id, "20260625_113655_096_point_112781_15134606")
            self.assertEqual(rows[0].point_id, "112781")
            self.assertEqual(rows[0].original_member, "frames/frame_000001_seq_000065999_offline_capture.png")
            self.assertTrue((output_dir / "original_images" / rows[0].export_name).is_file())
            self.assertTrue((output_dir / "masks" / rows[0].export_name).is_file())


if __name__ == "__main__":
    unittest.main()
