import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from download_sram_pdk import (
    PVT_CORNERS,
    SramError,
    build_payload,
    download_artifact,
    extract_artifact,
    validate_config,
)


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.args = SimpleNamespace(
            words=2048,
            bits=32,
            mux=8,
            vt=0,
            low_power=0,
            redundancy=0,
            word_write=0,
            bus_format=1,
            ring="ringless",
            corner="TT1P2V25CCTYP",
        )

    def test_build_payload_uses_api_field_names(self) -> None:
        self.assertEqual(
            build_payload(self.args),
            {
                "words": 2048,
                "bits": 32,
                "mux": 8,
                "vt": 0,
                "lowPower": 0,
                "redundancy": 0,
                "wordWrite": 0,
                "busFormat": 1,
                "ring": "ringless",
                "corner": "TT1P2V25CCTYP",
            },
        )

    def test_valid_boundary_configurations(self) -> None:
        for mux, (minimum, maximum, _, _, maximum_bits) in {
            4: (32, 4096, 32, 2, 160),
            8: (64, 8192, 64, 2, 80),
            16: (128, 16384, 128, 2, 40),
            32: (256, 32768, 256, 2, 20),
        }.items():
            config = build_payload(self.args)
            config.update(mux=mux, words=minimum, bits=2)
            validate_config(config)
            config.update(words=maximum, bits=maximum_bits)
            validate_config(config)

    def test_words_must_follow_mux_step(self) -> None:
        config = build_payload(self.args)
        config.update(words=65)
        with self.assertRaisesRegex(SramError, "step of 64"):
            validate_config(config)

    def test_enum_and_corner_values_are_checked(self) -> None:
        config = build_payload(self.args)
        config.update(vt=1)
        with self.assertRaisesRegex(SramError, "vt"):
            validate_config(config)

        config.update(vt=0, corner="invalid")
        with self.assertRaisesRegex(SramError, "corner"):
            validate_config(config)

        self.assertEqual(len(PVT_CORNERS), 8)


class ResponseAndDownloadTests(unittest.TestCase):
    def test_extract_artifact_validates_metadata(self) -> None:
        response = {
            "ok": True,
            "value": {
                "downloadUrl": "https://github.com/example/release.tar.gz",
                "mirrorUrl": "https://factory.openecos.com/mirror/release.tar.gz",
                "assetName": "sram.tar.gz",
                "sha256": "A" * 64,
            },
        }
        self.assertEqual(
            extract_artifact(response),
            (
                "https://github.com/example/release.tar.gz",
                "https://factory.openecos.com/mirror/release.tar.gz",
                "sram.tar.gz",
                "a" * 64,
            ),
        )

    def test_extract_artifact_rejects_path_traversal(self) -> None:
        response = {
            "ok": True,
            "value": {
                "downloadUrl": "https://github.com/example/release.tar.gz",
                "assetName": "../sram.tar.gz",
                "sha256": "a" * 64,
            },
        }
        with self.assertRaisesRegex(SramError, "plain file name"):
            extract_artifact(response)

    def test_download_verifies_hash_and_uses_mirror_when_needed(self) -> None:
        content = b"SRAM package fixture"
        expected = hashlib.sha256(content).hexdigest()
        calls = []

        def fake_download(url: str, destination: Path, **_: object) -> None:
            calls.append(url)
            if url == "https://primary.example/package.tar.gz":
                raise SramError("primary unavailable")
            destination.write_bytes(content)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "package.tar.gz"
            with patch("download_sram_pdk._download_once", side_effect=fake_download):
                installed = download_artifact(
                    [
                        "https://primary.example/package.tar.gz",
                        "https://mirror.example/package.tar.gz",
                    ],
                    destination,
                    expected,
                    timeout=1,
                    user_agent="test",
                )
            self.assertTrue(installed)
            self.assertEqual(calls, [
                "https://primary.example/package.tar.gz",
                "https://mirror.example/package.tar.gz",
            ])
            self.assertEqual(destination.read_bytes(), content)

            self.assertFalse(
                download_artifact(
                    ["https://primary.example/package.tar.gz"],
                    destination,
                    expected,
                    timeout=1,
                    user_agent="test",
                )
            )


if __name__ == "__main__":
    unittest.main()
