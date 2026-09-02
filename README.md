# ECOS Factory SRAM PDK Downloader

**Language:** English | [简体中文](README.zh-CN.md)

Generate and download an SRAM PDK macro package with selected parameters from [ECOS Factory ICS55 Single-Port SRAM](https://factory.openecos.com/ip/sram).

The script calls the SRAM Generator JSON API, uses the GitHub Release URL returned by the server, and verifies the downloaded file against the returned SHA-256 digest. It does not try to construct Release tags from SRAM parameters.

## Features

- Uses only the Python standard library; no third-party Python packages, `curl`, or `jq` are required
- Validates the current SRAM CONTRACT before making a request
- Supports previewing area, frequency, access time, and dynamic current
- Falls back to `mirrorUrl` if the primary GitHub download URL fails
- Follows HTTP redirects
- Downloads to a temporary file and atomically installs the file after digest verification
- Automatically extracts verified archives into a package-specific subdirectory under `downloads/`
- Supports batch generation from a JSON request file
- Checks the local cache before calling `generate` or downloading again
- Does not overwrite an existing file by default; skips the download if the existing file already has the expected digest
- Supports `--force` for an explicit re-download

## Requirements

- Python 3.10 or newer
- Network access to `https://factory.openecos.com`

The script does not require login credentials. The current web flow does not use a login token or CSRF token, but the service may add authentication, rate limits, or other validation in the future.

## Quick Start

Make the script executable:

```bash
chmod +x download_sram_pdk.py
```

Generate and download a package using the default configuration:

```bash
./download_sram_pdk.py
```

The default configuration is:

```text
words=2048
bits=32
mux=8
vt=0
lowPower=0
redundancy=0
wordWrite=0
busFormat=1
ring=ringless
corner=TT1P2V25CCTYP
```

By default, the archive and its extracted files are organized under a package-specific subdirectory of `./downloads/`:

```text
downloads/
`-- <asset-name-without-.tar.gz>/
    |-- <asset>.tar.gz
    `-- <extracted package files>
```

Use `--output-dir` to select another package root directory:

```bash
./download_sram_pdk.py \
  --words 4096 \
  --bits 64 \
  --mux 8 \
  --vt 0 \
  --low-power 0 \
  --redundancy 0 \
  --word-write 0 \
  --bus-format 1 \
  --ring ringless \
  --corner TT1P2V25CCTYP \
  --output-dir ./downloads
```

The options `--lowPower`, `--wordWrite`, and `--busFormat` are also accepted as aliases matching the API field names.

Show all command-line options:

```bash
./download_sram_pdk.py --help
```

## Batch Mode

Use `--batch` to read multiple SRAM configurations from one JSON file. The file can be either a JSON array or an object containing a `requests` array. Each request uses the API field names. Omitted fields use the same defaults as single-package mode.

Example `requests.json`:

```json
[
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
    "corner": "TT1P2V25CCTYP"
  },
  {
    "words": 4096,
    "bits": 64,
    "mux": 8,
    "vt": 2,
    "lowPower": 0,
    "redundancy": 0,
    "wordWrite": 0,
    "busFormat": 1,
    "ring": "ringless",
    "corner": "TT1P2V85CCTYP"
  }
]
```

Run the batch:

```bash
./download_sram_pdk.py \
  --batch requests.json \
  --output-dir ./downloads
```

Each request is validated and processed independently. A failed item does not stop later items; the command prints a final summary and returns exit code `1` if any item failed. `--batch` cannot be combined with `--preview`.

The script stores verified request metadata in `downloads/.sram-download-cache.json`. On later runs, an exact payload match is checked locally first. When the archive and its SHA-256 still match, the script reuses it without calling `generate` or downloading again. Use `--force` to bypass the local cache and regenerate every item.

Archives from the older flat layout, such as `downloads/TM..._V0L0R0_2048X32M8W0F1.tar.gz`, are also detected for `ringless` requests. They are moved into the current package subdirectory before extraction.

## Preview a Configuration

`--preview` calls `/api/ip/sram/preview`, prints the server JSON response, and does not generate or download a file:

```bash
./download_sram_pdk.py \
  --preview \
  --words 2048 \
  --bits 32 \
  --mux 8 \
  --corner TT1P2V25CCTYP
```

Typical response:

```json
{
  "ok": true,
  "value": {
    "instanceName": "TMHDSPZ055ABA_V0L0R0_2048X32M8W0F1",
    "corner": "TT1P2V25CCTYP",
    "source": "development-model",
    "areaUm2": 62437,
    "frequencyMhz": 545,
    "readAccessNs": 1.835,
    "dynamicCurrentUaPerMhz": 10.24
  }
}
```

## Parameters

| CLI option | JSON field | Meaning | Default |
| --- | --- | --- | --- |
| `--words` | `words` | SRAM depth | `2048` |
| `--bits` | `bits` | Data width | `32` |
| `--mux` | `mux` | Column mux | `8` |
| `--vt` | `vt` | `0` Balanced; `2` Higher speed; `5` Lower leakage | `0` |
| `--low-power` | `lowPower` | `0` Standard; `2` Nap/Retention/Power-down | `0` |
| `--redundancy` | `redundancy` | `0` None; `3` Column repair | `0` |
| `--word-write` | `wordWrite` | `0` Bit write enable; `1` Word write | `0` |
| `--bus-format` | `busFormat` | `1` uses `A[x]`; `0` uses `Ax` | `1` |
| `--ring` | `ring` | `ringless`, `port`, or `ring` | `ringless` |
| `--corner` | `corner` | PVT corner selected for preview | `TT1P2V25CCTYP` |

The script also accepts `--lowPower`, `--wordWrite`, and `--busFormat` as compatibility aliases.

## Valid Ranges

The valid `words` range and step depend on `mux`:

| `mux` | `words` range | Step | `bits` range |
| ---: | ---: | ---: | ---: |
| `4` | `32..4096` | `32` | `2..160` |
| `8` | `64..8192` | `64` | `2..80` |
| `16` | `128..16384` | `128` | `2..40` |
| `32` | `256..32768` | `256` | `2..20` |

Other valid values:

```text
vt:          0, 2, 5
lowPower:    0, 2
redundancy:  0, 3
wordWrite:   0, 1
busFormat:   0, 1
ring:        ringless, port, ring
```

Supported PVT corners:

```text
TT1P2V25CCTYP
TT1P2V85CCTYP
FF1P32VM40CCMIN
FF1P32V0CCMIN
FF1P32V125CCMIN
SS1P08VM40CCMAX
SS1P08V0CCMAX
SS1P08V125CCMAX
```

## API Flow

Preview request:

```text
POST https://factory.openecos.com/api/ip/sram/preview
Content-Type: application/json
```

Generate request:

```text
POST https://factory.openecos.com/api/ip/sram/generate
Content-Type: application/json
```

The request payload is:

```json
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
  "corner": "TT1P2V25CCTYP"
}
```

A successful generate response contains:

```json
{
  "ok": true,
  "value": {
    "downloadUrl": "https://github.com/.../asset.tar.gz",
    "mirrorUrl": "https://.../asset.tar.gz",
    "assetName": "asset.tar.gz",
    "sha256": "..."
  }
}
```

The GitHub Release tag in `downloadUrl` is an opaque digest generated by the server. Do not construct a download URL from the SRAM parameters; always use the returned `value.downloadUrl`.

## Files and Verification

After a successful generate request, the script:

1. Creates `downloads/<package-name>/` (or the directory selected by `--output-dir`)
2. Writes the archive to a temporary `.part` file in that package directory
3. Computes the actual SHA-256 digest
4. Compares it with `value.sha256`
5. Atomically renames the verified archive to `value.assetName`
6. Extracts regular files and directories into the same package directory

A typical SRAM macro package contains 14 files:

- 1 `.ds` file
- 1 `.lef` file
- 8 PVT `.lib` files
- 3 Verilog files
- 1 `.cpf` file

The archive is kept alongside the extracted files. When the tarball has a single top-level directory matching the archive name, that redundant directory level is removed during extraction. To download without extracting, use `--no-extract`:

```bash
./download_sram_pdk.py --output-dir ./downloads --no-extract
```

If the target archive already exists:

```bash
# Skip the download when the existing digest is correct
./download_sram_pdk.py --output-dir ./downloads

# Re-download and verify even when a file already exists
./download_sram_pdk.py --output-dir ./downloads --force
```

Additional useful options:

```bash
# Use a different API host
./download_sram_pdk.py --base-url https://example.invalid

# Set the HTTP timeout in seconds
./download_sram_pdk.py --timeout 120
```

## Testing

Run the local unit tests:

```bash
python3 -m unittest -v
```

The tests do not access the network. They cover parameter validation, generate-response metadata validation, mirror fallback, SHA-256 verification, safe archive extraction, and end-to-end package-directory organization.

## Notes

- The script embeds the currently known CONTRACT. Update `download_sram_pdk.py` if the website changes its legal ranges or fields.
- The service may return HTTP 401, 403, or 429. The script reports the server error and exits; it does not bypass authentication or rate limits.
- The public ICS55 PDK repository is released under Apache 2.0, but redistribution of a specific SRAM macro package should follow the latest ECOS Factory terms of use.
- Public repository: [icsprout55-pdk](https://github.com/openecos-projects/icsprout55-pdk).
