"""Verify offline navigation, filename escaping, and overwrite protection."""

from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from machine import load_program
from program.visualizations.gallery._gallery import write_gallery


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"}:
                self.links.append(value)


class GalleryTests(unittest.TestCase):
    def test_existing_output_is_untouched_without_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            index = output / "index.html"
            index.write_text("existing gallery", encoding="utf-8")
            with patch("program.visualizations.gallery._gallery.GraphvizRepresentation.encode") as render:
                with self.assertRaisesRegex(ValueError, "--clobber"):
                    write_gallery(Path("programs/json"), output)
                render.assert_not_called()
            self.assertEqual(index.read_text(encoding="utf-8"), "existing gallery")
            self.assertEqual(list(output.iterdir()), [index])

    def test_empty_source_does_not_create_gallery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "no JSON programs"):
                write_gallery(root, root / "output")
            self.assertFalse((root / "output").exists())

    @unittest.skipUnless(shutil.which("dot"), "Graphviz is not installed")
    def test_gallery_navigation_and_clobber_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "programs"
            source.mkdir()
            output = root / "gallery"
            program = load_program("programs/json/03_vector_axpy.json")
            program["name"] = '<script>alert("x")</script> & vectors'
            filename = '01 vector # & "demo".json'
            (source / filename).write_text(json.dumps(program), encoding="utf-8")
            command = [
                sys.executable, "-B", "-m", "program.visualizations.gallery", "gallery",
                "--programs-dir", str(source), "-o", str(output),
            ]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            for page in [output / "index.html", *output.glob("pages/*.html")]:
                content = page.read_text(encoding="utf-8")
                self.assertNotIn('<script>alert("x")</script>', content)
                parser = PageLinks()
                parser.feed(content)
                for link in parser.links:
                    self.assertNotIn("://", link)
                    self.assertTrue((page.parent / unquote(link)).is_file(), link)
            detail = (output / "pages" / f"{Path(filename).stem}.html").read_text(encoding="utf-8")
            self.assertIn('href="../index.html"', detail)
            self.assertIn("All programs", detail)
            original = (output / "index.html").read_bytes()
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertIn("--clobber", result.stderr)
            self.assertEqual((output / "index.html").read_bytes(), original)
            for flag in ("--clobber", "--c"):
                with self.subTest(flag=flag):
                    (output / "index.html").write_text("old gallery", encoding="utf-8")
                    result = subprocess.run(
                        [*command, flag], capture_output=True, text=True, timeout=30
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((output / "index.html").read_bytes(), original)
