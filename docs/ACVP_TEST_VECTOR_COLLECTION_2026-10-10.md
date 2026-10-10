# ML-KEM 公开测试向量收集记录（2026-10-10）

## 收集目的

把平台中原先只有少量内置测试向量的验证方式，扩展为可引用公开来源的大规模验证材料。该材料用于支撑题目第 1 条“利用公开或主办方提供的测试向量验证算法正确性”，并可在报告中作为“公开测试向量来源、数量、参数集覆盖范围”的证明。

## 来源

- 来源仓库：NIST ACVP Server
- 来源路径：`gen-val/json-files/`
- 本项目保存位置：`data/acvp/`
- 已保存数据集：
  - `ML-KEM-keyGen-FIPS203`
  - `ML-KEM-encapDecap-FIPS203`
  - `ML-KEM-encapDecap-FIPS203-tr1`

## 已收集规模

| 数据集 | prompt 项数 | expectedResults 项数 | internalProjection 项数 | 参数集覆盖 |
|---|---:|---:|---:|---|
| `ML-KEM-keyGen-FIPS203` | 75 | 75 | 75 | ML-KEM-512 / 768 / 1024，各 25 项 |
| `ML-KEM-encapDecap-FIPS203` | 165 | 165 | 165 | ML-KEM-512 / 768 / 1024，各 55 项 |
| `ML-KEM-encapDecap-FIPS203-tr1` | 195 | 195 | 195 | ML-KEM-512 / 768 / 1024，各 65 项 |

按 prompt 侧测试项计，当前共收集：

- keyGen：75 项；
- encap/decap 相关：360 项；
- 合计：435 项。

这已经满足“从 15 项扩展到 100 项以上公开测试向量来源”的材料要求。

## 与平台现有验证接口的关系

平台现有批量验证接口主要验证：

```text
输入：level + ct + sk
期望：ss
```

因此，能直接转换为平台批量验证 JSON 的，是 ACVP 中已经给出完整 `dk + c -> k` 的 decapsulation 项。目前已导出：

```text
data/acvp/platform_vectors/mlkem_decap_official_direct.json
```

该文件包含 60 条可直接导入平台验证器的官方 decapsulation 向量。

其余官方向量并不是“不能用”，而是属于 keyGen、encapsulation、key check 或 seed 驱动的确定性流程，需要接入底层 ACVP harness 或确定性 keyGen/encap 接口后再纳入自动验证。

## 后续接入建议

1. 报告中可以先写“已收集 NIST ACVP/FIPS203 公开向量 435 项，覆盖 ML-KEM-512/768/1024”。
2. 平台演示阶段优先展示：
   - 内置基础流程自测；
   - 官方 decapsulation 向量 60 项批量验证；
   - 公开向量库存清单 435 项。
3. 若需要把“实际自动验证数”提升到 100 项以上，应继续接入 mlkem-native 自带 ACVP 测试程序或确定性 API，把 seed 型 keyGen/encapsulation 向量也纳入自动验证。

## 使用脚本

统计全部向量：

```bash
python scripts/acvp_vector_inventory.py
```

导出可直接给平台批量验证接口使用的 decapsulation 向量：

```bash
python scripts/acvp_vector_inventory.py --export-decap --level all --limit 100 --out data/acvp/platform_vectors/mlkem_decap_official_direct.json
```

