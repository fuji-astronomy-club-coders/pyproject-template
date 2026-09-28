はい。現在の `pyproject.toml` を基準に、**Editor側は今までどおり厳しめ、CI側だけ低優先度チェックを緩和**する形なら、次の構成がきれいです。

現在の `pyproject.toml` では Ruff が `E/F/I/B/UP/SIM/PTH/A/D/ANN` を有効化し、basedpyright は `standard`、Python 3.13、`reportMissingImports = "error"` になっています。 

Ruffは `extend` による設定継承が可能で、子設定の `ignore` を追加できます。([Astral Docs][1])
basedpyrightもJSON設定から別の設定を継承できます。([BasedPyright][2])

## 推奨ディレクトリ構成

```text
SunSpotsEdge/
├── pyproject.toml
├── .github/
│   ├── ci/
│   │   ├── ruff.toml
│   │   └── basedpyright-ci.json
│   └── workflows/
│       └── ci.yml
└── ...
```

---

## 1. `.github/ci/ruff.toml`

まずは現在の `PTH` をCIの合否判定から外します。

```toml
# CI専用Ruff設定
#
# 通常の開発環境では pyproject.toml を使用する。
# CIでは、このファイルを通して低優先度のルールを緩和する。

extend = "../../pyproject.toml"

[lint]
# pyproject.toml のルールを維持したまま、
# CIではPathlib移行チェックを合否判定から除外する。
ignore = [
    "PTH",
]
```

これが重要なところです。

`select` をここで再定義していないので、

```text
pyproject.toml
    ↓
E F I B UP SIM PTH A D ANN
    ↓
.github/ci/ruff.toml
    ↓
PTHだけignore
    ↓
E F I B UP SIM A D ANN
```

となります。

Ruffの `ignore` は `PTH` のようなプレフィックスを指定して、そのグループ全体を対象外にできます。([Astral Docs][3])

### 将来的に緩和対象を増やす場合

例えば `D` と `ANN` もCIでは厳しくしない、と判断したら、

```toml
[lint]
ignore = [
    "PTH",
    "D",
    "ANN",
]
```

とするだけです。

私は最初は **PTHだけ**をCIから外すことを推奨します。`F`、`E`、`B`、`I`、`UP`などを緩めると、CIの品質チェックとしての意味がかなり変わるためです。

---

# 2. `.github/ci/basedpyright-ci.json`

現在の設定を基本的に維持し、CI用設定を明示的に分離します。

```json
{
    "extends": "../../pyproject.toml",

    "include": [
        "pyproject"
    ],

    "exclude": [
        "**/__pycache__",
        ".venv",
        "venv",
        "build",
        "dist"
    ],

    "typeCheckingMode": "standard",
    "pythonVersion": "3.13",

    "reportMissingImports": "error",
    "reportMissingTypeStubs": false
}
```

ただし、**ここには1点注意があります。**

現在の `pyproject.toml` の `include` は、

```toml
include = [
    "pyproject",
]
```

となっています。

これはSunSpotsEdgeの実際のソースディレクトリが本当に `pyproject/` なのか確認した方がいいです。

もし実際の構成が、

```text
src/
    SunSpotsEdge/
```

なら、

```json
"include": [
    "src"
]
```

などに変更する必要があります。

**今回提供された `pyproject.toml` だけからは、実際のソースディレクトリ構成までは判断できません。**

---

# 3. `.github/workflows/ci.yml`

現在のCIは、

```yaml
ruff check .
ruff format --check .
basedpyright
```

となっています。

これを次のようにします。

```yaml
name: CI

on:
  push:
    branches:
      - main
      - master

  pull_request:

jobs:
  lint-and-type-check:
    name: Lint & Type Check
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.13"
          cache: "pip"

      - name: Upgrade pip
        run: python -m pip install --upgrade pip

      - name: Install project and development dependencies
        run: python -m pip install -e ".[dev]"

      - name: Check pyproject dependencies
        run: python generate_dependencies.py --check

      - name: Ruff check
        run: ruff check . --config .github/ci/ruff.toml

      - name: Ruff format check
        run: ruff format --check . --config .github/ci/ruff.toml

      - name: basedpyright
        run: basedpyright --project .github/ci/basedpyright-ci.json
```

Ruffは `--config` で使用する設定ファイルを直接指定できます。([Astral Docs][1])
basedpyrightは `--project` で使用する設定ファイルを指定できます。([BasedPyright][4])

---

# 4. この構成でどう動くか

最終的にはこうなります。

```text
                    SunSpotsEdge
                         │
              ┌──────────┴──────────┐
              │                     │
          開発者PC                 GitHub CI
              │                     │
      pyproject.toml          .github/ci/
              │               ├─ ruff.toml
              │               └─ basedpyright-ci.json
              │                     │
       ┌──────┴──────┐       ┌──────┴──────┐
       │             │       │             │
      Ruff       basedpyright Ruff     basedpyright
       │             │       │             │
       ▼             ▼       ▼             ▼
  PTHも診断      standard  PTH除外      CI用設定
```

つまり、

### Editor

```text
PTH001
PTH002
PTH003
...
```

も表示されます。

### CI

```text
E/F/I/B/UP/SIM/A/D/ANN
```

はチェックされますが、

```text
PTH
```

はCIのfailure要因になりません。

---

## 5. 「警告として表示」の意味について

ここは前の質問との関係で重要です。

今回の構成では、

> **EditorではPTHを表示する**

ことはできますが、

> **CIではPTHをwarningとして表示しつつ、そのwarningだけでは失敗させない**

という動作ではありません。

CI側では **PTHそのものをignore** します。

一方、basedpyrightには診断レベルとして `error` / `warning` 等を設定する仕組みがあります。([BasedPyright][2])

そのため、

```text
Ruff
  └─ Editor: 診断を表示
  └─ CI: 低優先度ルールをignore

basedpyright
  └─ Editor: error / warningを細かく設定
  └─ CI: error中心
```

という役割分担ができます。

---

## 6. 私なら最終的にはこうします

現在のSunSpotsEdgeなら、まずはこの3段階にします。

| チェック         | Editor   | CI         |
| ------------ | -------- | ---------- |
| `E`          | 表示       | failure    |
| `F`          | 表示       | failure    |
| `I`          | 表示       | failure    |
| `B`          | 表示       | failure    |
| `UP`         | 表示       | failure    |
| `SIM`        | 表示       | failure    |
| `PTH`        | **表示**   | **ignore** |
| `A`          | 表示       | failure    |
| `D`          | 表示       | failure    |
| `ANN`        | 表示       | failure    |
| basedpyright | standard | standard   |

この方針なら、**コーダーには「直した方がいい箇所」を全部見せつつ、CIでは本当に重要な問題だけをmainへの品質ゲートにする**ことができます。

なお、現在の `pyproject.toml` のプロジェクト名が `pyproject-template` になっている点は、SunSpotsEdge本体の設定としては一度確認した方がよいです。

この4ファイルをそのままリポジトリに入れるなら、**次は実際のSunSpotsEdgeのディレクトリ構成（特に `pyproject/` がソースなのか）に合わせて `include` を確定させる**のが最後の調整になります。

[1]: https://docs.astral.sh/ruff/configuration/?utm_source=chatgpt.com "Configuring Ruff | Ruff"
[2]: https://docs.basedpyright.com/v1.18.4/configuration/config-files/?utm_source=chatgpt.com "Config files - basedpyright"
[3]: https://docs.astral.sh/ruff/settings/?utm_source=chatgpt.com "Settings | Ruff"
[4]: https://docs.basedpyright.com/latest/configuration/command-line/?utm_source=chatgpt.com "Command line - basedpyright"
