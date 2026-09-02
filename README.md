# ECOS Factory SRAM PDK Downloader

从 [ECOS Factory ICS55 Single-Port SRAM](https://factory.openecos.com/ip/sram) 生成并下载指定参数的 SRAM PDK 宏包。

脚本调用 SRAM Generator 的 JSON API，读取服务端返回的 GitHub Release 下载地址，不自行拼接 Release tag，并在下载完成后校验 SHA-256。

## 特性

- 仅使用 Python 标准库，不需要安装第三方 Python 包、`curl` 或 `jq`
- 在发起请求前校验当前 SRAM CONTRACT 的参数范围
- 支持预览面积、频率、访问时间和动态电流
- 支持 GitHub 下载地址失败时使用 `mirrorUrl` 备用地址
- 支持 HTTP 重定向
- 下载到临时文件，摘要校验成功后再原子替换目标文件
- 默认不会覆盖已有文件；已有文件摘要正确时会跳过下载
- 支持 `--force` 强制重新下载

## 环境要求

- Python 3.10 或更高版本
- 能访问 `https://factory.openecos.com`

脚本不需要登录信息。当前网页流程未使用登录 token 或 CSRF token，但服务端未来可能增加登录、限流或其他校验。

## 快速开始

为脚本添加可执行权限：

```bash
chmod +x download_sram_pdk.py
```

使用默认配置生成并下载：

```bash
./download_sram_pdk.py
```

默认配置为：

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

下载的 `.tar.gz` 文件默认保存到当前目录。可以用 `--output-dir` 指定目录：

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

也可以使用接口字段风格的别名 `--lowPower`、`--wordWrite` 和 `--busFormat`。

查看所有命令行选项：

```bash
./download_sram_pdk.py --help
```

## 预览配置

`--preview` 只调用 `/api/ip/sram/preview`，打印服务端 JSON，不会生成或下载文件：

```bash
./download_sram_pdk.py \
  --preview \
  --words 2048 \
  --bits 32 \
  --mux 8 \
  --corner TT1P2V25CCTYP
```

典型响应：

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

## 参数说明

| 命令行参数 | JSON 字段 | 含义 | 默认值 |
| --- | --- | --- | --- |
| `--words` | `words` | SRAM 深度 | `2048` |
| `--bits` | `bits` | 数据宽度 | `32` |
| `--mux` | `mux` | Column mux | `8` |
| `--vt` | `vt` | `0` Balanced；`2` Higher speed；`5` Lower leakage | `0` |
| `--low-power` | `lowPower` | `0` Standard；`2` Nap/Retention/Power-down | `0` |
| `--redundancy` | `redundancy` | `0` None；`3` Column repair | `0` |
| `--word-write` | `wordWrite` | `0` 位写使能；`1` 字写 | `0` |
| `--bus-format` | `busFormat` | `1` 使用 `A[x]`；`0` 使用 `Ax` | `1` |
| `--ring` | `ring` | `ringless`、`port` 或 `ring` | `ringless` |
| `--corner` | `corner` | 预览所选 PVT corner | `TT1P2V25CCTYP` |

`--lowPower`、`--wordWrite` 和 `--busFormat` 是对应参数的兼容别名。

## 合法范围

`words` 的范围和步长取决于 `mux`：

| `mux` | `words` 范围 | 步长 | `bits` 范围 |
| ---: | ---: | ---: | ---: |
| `4` | `32..4096` | `32` | `2..160` |
| `8` | `64..8192` | `64` | `2..80` |
| `16` | `128..16384` | `128` | `2..40` |
| `32` | `256..32768` | `256` | `2..20` |

其他合法值：

```text
vt:          0, 2, 5
lowPower:    0, 2
redundancy:  0, 3
wordWrite:   0, 1
busFormat:   0, 1
ring:        ringless, port, ring
```

PVT corner：

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

## API 流程

预览请求：

```text
POST https://factory.openecos.com/api/ip/sram/preview
Content-Type: application/json
```

生成请求：

```text
POST https://factory.openecos.com/api/ip/sram/generate
Content-Type: application/json
```

请求 JSON 字段为：

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

生成成功时，脚本读取以下响应字段：

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

`downloadUrl` 中的 GitHub Release tag 是服务端生成的 opaque digest。不要根据 SRAM 参数自行拼接下载地址，应始终使用接口返回的 `downloadUrl`。

## 文件与校验

下载成功后，脚本会：

1. 将文件写入输出目录中的临时 `.part` 文件
2. 计算实际 SHA-256
3. 与接口返回的 `value.sha256` 比较
4. 校验成功后原子替换为 `value.assetName`

通常的 SRAM 宏包包含 14 个文件：

- 1 个 `.ds`
- 1 个 `.lef`
- 8 个 PVT `.lib`
- 3 个 Verilog 文件
- 1 个 `.cpf`

脚本只负责下载和校验，不会自动解压 tar.gz。

若目标文件已存在：

```bash
# 摘要一致时直接跳过
./download_sram_pdk.py --output-dir ./downloads

# 无论现有摘要如何，都重新下载并校验
./download_sram_pdk.py --output-dir ./downloads --force
```

## 测试

运行本地单元测试：

```bash
python3 -m unittest -v
```

测试不访问外网，覆盖参数校验、API 响应元数据校验、备用下载地址和 SHA-256 校验流程。

## 注意事项

- 脚本内置的是当前已知 CONTRACT。如果网站更新合法范围或字段，需要同步更新 `download_sram_pdk.py`。
- 服务端可能返回 HTTP 401、403 或 429。脚本会打印接口返回的错误并退出，不会绕过登录或限流策略。
- ICS55 PDK 公开仓库按 Apache 2.0 发布，但具体 SRAM 宏包是否允许再分发，应以 ECOS Factory 最新使用条款为准。
- 相关公开仓库：[icsprout55-pdk](https://github.com/openecos-projects/icsprout55-pdk)。
