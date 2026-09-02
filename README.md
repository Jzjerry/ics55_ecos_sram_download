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

The `.tar.gz` file is saved in the current directory by default. Use `--output-dir` to select another directory:

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

After receiving the package, the script:

1. Writes the response to a temporary `.part` file in the output directory
2. Computes the actual SHA-256 digest
3. Compares it with `value.sha256`
4. Atomically renames the verified file to `value.assetName`

A typical SRAM macro package contains 14 files:

- 1 `.ds` file
- 1 `.lef` file
- 8 PVT `.lib` files
- 3 Verilog files
- 1 `.cpf` file

The script downloads and verifies the tarball but does not extract it automatically.

If the target file already exists:

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

The tests do not access the network. They cover parameter validation, generate-response metadata validation, mirror fallback, and SHA-256 verification.

## Notes

- The script embeds the currently known CONTRACT. Update `download_sram_pdk.py` if the website changes its legal ranges or fields.
- The service may return HTTP 401, 403, or 429. The script reports the server error and exits; it does not bypass authentication or rate limits.
- The public ICS55 PDK repository is released under Apache 2.0, but redistribution of a specific SRAM macro package should follow the latest ECOS Factory terms of use.
- Public repository: [icsprout55-pdk](https://github.com/openecos-projects/icsprout55-pdk).
