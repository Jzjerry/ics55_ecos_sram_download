import hashlib
import io
import json
import tarfile
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
    extract_archive,
    extract_artifact,
    find_cached_artifact,
    load_batch_requests,
    main,
    package_directory_name,
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

    def test_load_batch_requests_accepts_list_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "requests.json"
            request_path.write_text(
                json.dumps(
                    [
                        {"words": 2048, "bits": 32, "mux": 8},
                        {"words": 4096, "bits": 64, "mux": 8, "vt": 2},
                    ]
                ),
                encoding="utf-8",
            )
            requests = load_batch_requests(request_path)

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["lowPower"], 0)
        self.assertEqual(requests[1]["vt"], 2)

    def test_load_batch_requests_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "requests.json"
            request_path.write_text(
                json.dumps([{"words": 2048, "bits": 32, "mux": 8, "label": "demo"}]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SramError, "unsupported fields: label"):
                load_batch_requests(request_path)


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

    def test_package_directory_name_removes_archive_suffix(self) -> None:
        self.assertEqual(package_directory_name("macro.tar.gz"), "macro")
        self.assertEqual(package_directory_name("macro.tgz"), "macro")
        self.assertEqual(package_directory_name("macro.bin"), "macro")

    def test_extract_archive_writes_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "macro.tar.gz"
            destination = root / "macro"
            content = b"library content"

            with tarfile.open(archive_path, "w:gz") as archive:
                directory = tarfile.TarInfo("lib")
                directory.type = tarfile.DIRTYPE
                archive.addfile(directory)
                library = tarfile.TarInfo("lib/tt.lib")
                library.size = len(content)
                archive.addfile(library, io.BytesIO(content))

            self.assertEqual(extract_archive(archive_path, destination), 1)
            self.assertEqual((destination / "lib" / "tt.lib").read_bytes(), content)

    def test_extract_archive_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "macro.tar.gz"
            destination = root / "macro"

            with tarfile.open(archive_path, "w:gz") as archive:
                escaped = tarfile.TarInfo("../outside.txt")
                escaped.size = 4
                archive.addfile(escaped, io.BytesIO(b"nope"))

            with self.assertRaisesRegex(SramError, "unsafe archive member path"):
                extract_archive(archive_path, destination)
            self.assertFalse((root / "outside.txt").exists())

    def test_main_downloads_and_extracts_to_package_directory(self) -> None:
        package_content = b"macro file"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture_archive = root / "fixture.tar.gz"
            with tarfile.open(fixture_archive, "w:gz") as archive:
                member = tarfile.TarInfo("README.txt")
                member.size = len(package_content)
                archive.addfile(member, io.BytesIO(package_content))

            archive_bytes = fixture_archive.read_bytes()
            response = {
                "ok": True,
                "value": {
                    "downloadUrl": "https://github.com/example/fixture.tar.gz",
                    "assetName": "fixture.tar.gz",
                    "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                },
            }

            def fake_download(_: str, destination: Path, **__: object) -> None:
                destination.write_bytes(archive_bytes)

            output_dir = root / "downloads"
            with patch("download_sram_pdk.post_json", return_value=response), patch(
                "download_sram_pdk._download_once", side_effect=fake_download
            ):
                exit_code = main(["--output-dir", str(output_dir)])

            package_dir = output_dir / "fixture"
            self.assertEqual(exit_code, 0)
            self.assertTrue((package_dir / "fixture.tar.gz").exists())
            self.assertEqual((package_dir / "README.txt").read_bytes(), package_content)

    def test_batch_processes_requests_and_reuses_local_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_dir = root / "downloads"
            batch_path = root / "requests.json"
            batch_path.write_text(
                json.dumps(
                    {
                        "requests": [
                            {"words": 2048, "bits": 32, "mux": 8},
                            {"words": 4096, "bits": 64, "mux": 8},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            archive_bytes_by_url = {}
            response_by_words = {}
            for words, asset_name, content in (
                (2048, "spec-a.tar.gz", b"spec a"),
                (4096, "spec-b.tar.gz", b"spec b"),
            ):
                fixture_archive = root / asset_name
                with tarfile.open(fixture_archive, "w:gz") as archive:
                    member = tarfile.TarInfo(asset_name.removesuffix(".tar.gz") + "/README.txt")
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
                archive_bytes = fixture_archive.read_bytes()
                url = f"https://github.com/example/{asset_name}"
                archive_bytes_by_url[url] = archive_bytes
                response_by_words[words] = {
                    "ok": True,
                    "value": {
                        "downloadUrl": url,
                        "assetName": asset_name,
                        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                    },
                }

            def fake_post(_: str, payload: dict[str, object], **__: object) -> dict[str, object]:
                return response_by_words[payload["words"]]

            def fake_download(url: str, destination: Path, **__: object) -> None:
                destination.write_bytes(archive_bytes_by_url[url])

            with patch("download_sram_pdk.post_json", side_effect=fake_post), patch(
                "download_sram_pdk._download_once", side_effect=fake_download
            ):
                self.assertEqual(
                    main(["--batch", str(batch_path), "--output-dir", str(output_dir)]),
                    0,
                )

            for name, content in (("spec-a", b"spec a"), ("spec-b", b"spec b")):
                self.assertEqual(
                    (output_dir / name / "README.txt").read_bytes(), content
                )
            self.assertTrue((output_dir / ".sram-download-cache.json").exists())

            with patch("download_sram_pdk.post_json", side_effect=AssertionError("API called")), patch(
                "download_sram_pdk._download_once", side_effect=AssertionError("download called")
            ):
                self.assertEqual(
                    main(["--batch", str(batch_path), "--output-dir", str(output_dir)]),
                    0,
                )

    def test_main_reuses_and_organizes_legacy_flat_archive(self) -> None:
        asset_name = "TMHDSPZ055ABA_V0L0R0_2048X32M8W0F1.tar.gz"
        content = b"legacy macro"
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "downloads"
            output_dir.mkdir()
            archive_path = output_dir / asset_name
            with tarfile.open(archive_path, "w:gz") as archive:
                member = tarfile.TarInfo(asset_name.removesuffix(".tar.gz") + "/README.txt")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))

            with patch("download_sram_pdk.post_json", side_effect=AssertionError("API called")), patch(
                "download_sram_pdk._download_once", side_effect=AssertionError("download called")
            ):
                self.assertEqual(main(["--output-dir", str(output_dir)]), 0)

            package_dir = output_dir / asset_name.removesuffix(".tar.gz")
            self.assertFalse(archive_path.exists())
            self.assertEqual((package_dir / "README.txt").read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
