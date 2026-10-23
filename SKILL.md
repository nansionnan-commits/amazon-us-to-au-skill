---
name: amazon-us-to-au-listing
description: 亚马逊跨站复制 Listing（US→AU，澳洲站）。当老板要"把 US 产品复制到 AU / 澳洲站上传 / US 转 AU / 传这几个 ASIN 到澳洲"时使用。支持张奥迪、刘冬冬两店（--store 切换）。自动取产品类型、按 AU 公式换算价格（(US 价+5.99)×1.43−12.99）、Generic 品牌 + GTIN 豁免 + COLOR 变体上传，内置 AU 与 CA 的全部字段差异铁律，开完回验。
---

# 亚马逊跨站复制 Listing（US → AU）

把 US 站 ASIN 自动复制到 AU 站（澳洲站）上架。**AU 与 CA 的字段结构不一样**，本 skill 的所有坑已固化进脚本默认值，直接跑即可，不要手改公式和字段。

## 触发条件

老板说「复制 listing 到 AU」「US 转 AU」「传这几个 ASIN 到澳洲站」「把今天新上架传到 AU」等。

## 一键用法

```bash
cd .workbuddy/skills/amazon-us-to-au-listing/scripts

python run_au.py B0XXX,B0YYY,B0ZZZ              # 默认张奥迪，给定 US 站 ASIN（逗号分隔）
python run_au.py --today                        # 自动抓 US 站当天(UTC)新上架
python run_au.py --today --dry-run              # 只构建+校验，不提交（推荐第一次先用这个）
python run_au.py --store liudongdong --today     # 指定店铺（默认 zhangaodi）
```

单组调试也可以直接用：
```bash
python build_au.py --store liudongdong --parent <US父SKU> --child <US子SKU> [--dry-run|--run]
```

## 多店支持

`--store` 可选 `zhangaodi`（默认）/ `liudongdong`，配置集中在 `scripts/stores.py`，新增店铺只改这一个文件。

| 项 | 张奥迪 zhangaodi | 刘冬冬 liudongdong |
|---|---|---|
| 凭证文件 | `sp-api-workbuddy奥迪.txt` | `sp-api-workbuddy刘冬冬.txt` |
| US(NA) seller | `A1ON6BNVRPOF3T` | `A37KA1V9F4DYXQ` |
| AU seller | **`A36XI3SU3OR6IQ`** | `A2U23KQN97ZU0T` |
| US 品牌 | `EAOEIHD` | **`Generic`** |
| SKU 命名 | 无站点后缀 → 追加 `-AU` | `-US`/`-us` **替换**为 `-AU`/`-au` |

⚠️ 两店凭证文件里 seller_id 行**都是空的**，seller_id 必须手抄，不能从文件读。

## 完整流程

1. 反查 SKU + PT（`searchListingsItems` 翻页拿全量 `asin→sku`、`sku→productType`）
2. 父子分组（`catalog/relationships` 判断父/子/独立）
3. 按 PT 拉 AU schema（自动缓存到 `scripts/_au_schema_<PT>.json`），按 schema required 做必填校验
4. 构建 AU patch（`build_au.build`，铁律全部固化在代码里）
5. 上传（变体组先父后子；独立 listing 单 SKU 可售）
6. 回验（等 90s，逐 SKU 查 ASIN / 状态 / 错误码）

## 铁律（血泪教训，务必照抄，不要改）

### 一、身份与端点（最容易错、最难排查）

- **⚠️ 张奥迪 AU 真实 seller_id = `A36XI3SU3OR6IQ`（永远不能再错）**。凭证文件 `D:\广告上传表格\sp-api-workbuddy奥迪.txt` 第17行 seller_id 是**空的**，这个值只能手抄。曾记成 `A36XI3OR6IQ`（漏 `SU3`）。
- **🔪 最阴的陷阱：seller_id 写错时，Orders API 照样返回 200**（Amazon 对 Orders 宽容、对 Listings 严格），极易误判成"AU 站没开通/没权限"。
  **→ 判断 AU 通不通，必须用 Listings API 或 `/sellers/v1/marketplaceParticipations`，不能拿 Orders 200 当证据。**
- 刘冬冬 AU seller_id = `A2U23KQN97ZU0T`（正确）。AU marketplace = `A39IBJ37TRP1C6`，端点 `sellingpartnerapi-fe.amazon.com`，Reports 版本 2021-06-30。
- token：凭证文件**第 1 个 refresh_token = AU 站，第 2 个 = NA(US/CA/MX)**，和直觉相反，搞反全 403。

### 二、价格（老板 2026-10-16 最新定版）

- `target = US 售价 + 5.99`（US 站运费）
- **`AU 报价 = round_to_99(target × 1.43 − 12.99)`**（"→.99" = `int(x+0.5) - 0.01`；12.99 是 AU 站运费）
- `list_price = 报价 × 1.7`
- 币种 **AUD**，不是 USD。
- 实测换算（改版后）：

| US 售价 | target | AU 报价 | 划线价 |
|---|---|---|---|
| $12.99 | 18.98 | **A$13.99** | A$23.78 |
| $13.99 | 19.98 | **A$15.99** | A$27.18 |
| $18.99 | 24.98 | **A$22.99** | A$39.08 |
| $19.99 | 25.98 | **A$23.99** | A$40.78 |

> ⚠️ 2026-10-16 只把乘数 **1.5 → 1.43**，公式结构没变。恒量在 `build_au.AU_MULTIPLIER`，改价只改这一处。

### 三、字段结构（AU ≠ CA，3 个实测打回的坑）

1. **`list_price` 必须用 `value_with_tax`**（CA 用 `value`）→ 用错报 **99022**。
2. **`purchasable_offer` 不要带 `quantity`**（CA 带）→ 带了报 **90000900**，整个价格字段被 Amazon 忽略，listing 会没价格。
3. **`merchant_shipping_group` 不能用 US 的模板 UUID** → 报 **90244**；AU 模板按类目分配、彼此不通用 → **去掉让 Amazon 自动分配**（回读会拿到类似 `4ba542d4-039c-4f91-ac77-1a556e92e583` 的值）。

### 四、必填字段差异

- **AU 比 CA 多一个必填 `recommended_browse_nodes`**（CA 不在 required）。不给会 INVALID，脚本里不传 `--browse-node` 且速查表没有该 PT 时会**主动报错停下**，不允许瞎猜。
- AU schema 里**没有** `manufacturer_contact_information` / `item_type_keyword` → 必须剔除（脚本按 schema properties 白名单过滤，自动处理）。
- AU 必填全集（实测 SKIN_CLEANING_BRUSH，脚本按 PT 动态取，不要硬编码）：`brand / bullet_point / country_of_origin / item_name / product_description / recommended_browse_nodes / supplier_declared_dg_hz_regulation`。

### 五、browse node（站点专属，不能套 US）

- **AU 的 browse node 与 US 不通用**（同一数字 ID 在不同站点含义可能完全不同）。
- **取法（推荐，2026-10-17 起）：用 AU 竞品的 ASIN 反查分类树** —— 比翻前台 BSR 快且准（AU 前台很多 listing 不显示 BSR）：
  ```bash
  python _node_from_asin.py <store> <AU竞品ASIN>
  # 返回 Catalog Items classifications 链，最内层 classificationId 就是要的 node
  ```
  竞品 ASIN 从 `https://www.amazon.com.au/s?k=<关键词>` 拿。
- 老办法（前台 BSR）：详情页 Best Sellers Rank 里的类目链接 `/gp/bestsellers/<dept>/<node>`。
- 已实测录入速查表（`build_au.AU_BROWSE_NODES`）：
  - **SKIN_CLEANING_BRUSH（洁肤刷/背刷）= `5150180051`**（Beauty > Body Brushes）
  - **DECORATIVE_SIGNAGE（木制圣诞门挂）= `10331504051`**（Home > Christmas Wreaths）
  - **APPENDAGE_WARMER（电热手套）= `5047994051`**（Clothing > Sport Specific Clothing > Skiing > Men > Gloves）
  - **HOLE_PUNCH（手工打孔器）= `5269423051`**（Home > Arts & Crafts > Crafting > Paper & Paper Crafts > Punches）
  - **FUNNEL（罐装漏斗）= `5016687051`**（10-22 取自 AU 竞品 B0HNNJ11M7，唯这个 PT 目前真必填 node）
  - 备用（对应 PT 的 required 目前不含 node，先录着）：GARLAND `4976017051`、PET_TOY `5848095051`、PET_APPAREL `5265199051`、STORAGE_COVER `5707689051`
- **PT=PRODUCT 时用 `_probe_pt.py` 一次拿到「真实 PT + node」**（搜 AU 同款竞品 → `productTypes` / `classifications` 最内层），比翻前台快。
- **新 PT 第一次用时**：按上面方法拿到 node，先补进 `build_au.AU_BROWSE_NODES`，再跑。

### 六、其余通用规则（同 CA）

- 品牌：US=`EAOEIHD` → AU=`Generic`；`manufacturer` 为空补 `Generic`。
- `language_tag` = **`en_AU`**（填 en_US 会全字段 100720）。
- **`item_name` 必须 ≤ 75 字符**（AU 硬限制，超长报 **100476** 阻塞出 ASIN）。脚本 `trim_au_title()` 自动处理：先剥尾部括号段，再按词边界截断。
- `variation_theme` = `COLOR`（子体名填在 `color.value`）。
- 库存 500、处理 2 天、`fulfillment_channel_code` = `DEFAULT`、`country_of_origin` = `CN`。
- `supplier_declared_has_product_identifier_exemption` = `true`（GTIN 豁免）；不填 `externally_assigned_product_identifier` / `merchant_suggested_asin`。
- `unit_count.type.value` 统一转小写（US 大写 "Count"，AU 枚举认小写）。
- `item_name` 去掉品牌前缀（品牌表见 `stores.BRAND_PREFIXES`）。
- **SKU 命名按店不同**（见 `stores.to_au_sku`）：张奥迪追加 `-AU`；刘冬冬把 `-US`/`-us` 替换成 `-AU`/`-au`。
- 图片跨站直接复用 US CDN URL（`main_product_image_locator` / `other_product_image_locator_*` 透传）。
- **issues 有「粘性」**：字段错一次，重传正确值旧 issues 不刷新 → 只能删除重建（DELETE 子→父→等 ≥90s→PUT 父→子），或换新 SKU。

## 脚本

| 文件 | 作用 |
|---|---|
| `scripts/stores.py` | **店铺配置表**（凭证文件 / seller_id / token 下标 / 品牌 / SKU 后缀规则）；新增店铺只改这里 |
| `scripts/auth.py` | US 源站 LWA 认证（NA 端点，`set_store()` 切店） |
| `scripts/auth_au.py` | AU 目标站客户端（FE 端点，**seller_id 铁律在 stores.py**） |
| `scripts/build_au.py` | 构建 patch（含全部铁律 + schema 驱动的必填/字段裁剪 + browse node 速查表） |
| `scripts/run_au.py` | 一键入口（反查→分组→上传→回验） |
| `scripts/_verify.py` | 复验：`python _verify.py --store <店> SKU...`（**必须带 --store**，默认 zhangaodi，查错店会全是 404） |
| `scripts/_rerun.py` | 按 US SKU 补跑单组：`python _rerun.py <店> <US父SKU> [子SKU1,子SKU2]` |
| `scripts/_node_from_asin.py` | 反查 AU browse node：`python _node_from_asin.py <店> <AU竞品ASIN>` |
| `scripts/_find_node.py` | 从自家 AU 存量 listing 反查同 PT 的 node（仅当自家有同 PT 时可用） |
| `scripts/_rerun_batch.py` | 批量补跑：`python _rerun_batch.py <店> "<父>:<子1,子2>" "<独立SKU>"`，全部传完只等一次 120s（比逐个跑快） |
| `scripts/_probe_pt.py` | 反查 AU 真实 PT + browse node：`python _probe_pt.py <店> <US SKU...>`（US PT=PRODUCT 时必用） |
| `scripts/_try_batt.py` | 试探电池类校验（90004205）的合法枚举值，一次试多个 |

## 常见错误码速查

| 错误码 | 含义 | 处理 |
|---|---|---|
| 400 InvalidInput | **seller_id 写错**（如漏 SU3）或 marketplaceIds 不归该 seller | 核对 `A36XI3SU3OR6IQ`；别用 Orders 200 自证 |
| 99022 | `list_price` 少了 `value_with_tax` | AU 必须 `value_with_tax`，不是 `value` |
| 90000900 | `purchasable_offer` 带了不适用字段 | 去掉 `quantity` |
| 90244 | `merchant_shipping_group` 模板 UUID 不适用 | 去掉让 Amazon 自动分配 |
| 100720 | language_tag 错 | 改 `en_AU` + 删除重建 |
| 缺 `recommended_browse_nodes` | AU 必填 | 去 AU 前台竞品 BSR 拿 node，补进速查表 |
| 8560 / 13013 | **该 PT 的 AU 可售 SKU 必须有真实 UPC** | GTIN 豁免对它不生效。**已实测：`ADVENT_CALENDAR`、`COSMETIC_NAIL_SET`、`APPENDAGE_WARMER`、`SLEEPING_BAG`、`HOLE_PUNCH` 都中招** → 后台申请该类目豁免或提供 UPC |
| 4000004 | `productType` = 通用 `PRODUCT` 时 AU **不允许建品**（Creating products is not supported with the 'PRODUCT' Amazon product type） | US 侧 PT 被记成 PRODUCT 时，用 `_probe_pt.py` 搜 AU 同款竞品取真实 PT，补进 `build_au.PT_OVERRIDE`。⚠️ 仅当 US 仍为 PRODUCT 时纠正：Amazon 会异步把 PT 改成更贴切的类目（如 10-22 水龙头罩 PRODUCT→FAUCET），那时以 Amazon 判断为准 |
| 90004205 | `battery_installation_device_type` 与 `battery.cell_composition` 冲突：**内置锂电商品填 `installed_in_equipment` 一律被打回** | 统一填 `not_installed`（实测 not_installed / installed_in_vehicle / installed_in_vessel 均可过）。脚本 `AU_BATTERY_DEFAULTS` 已固化 |
| 18027 | **主图含文字/logo/水印**，该 PT 不允许 → listing 被压制（`status` 为空，但 ASIN 已分配） | 换一张无文字主图重传；不属于脚本能修的范围，需美工出图 |
| 18448 | 缺 `style` 等非阻塞属性（WARNING） | 不影响展示，可不处理 |
| 100336 | 尺寸低于 AU 类目下限（如 JUICER 高 1.1in < 1.3in） | **只是 WARNING，不阻塞**，listing 照常出 |
| 100521 | Amazon 正在审核该 listing（最长 48h） | **不是失败**，等审核，无需改动；到点未通过会再报 issue |
| 90220（电气类） | AU 规则强制 `power_plug_type` + `accepted_voltage_frequency`，源 listing 没有 | 脚本已按 `AU_ELEC_DEFAULTS` 自动补 `no_plug` + `100v_240v_50hz_60hz`；真插头产品需按 PT 覆盖成 `type_i_3pin_au` |
| 90220（保修/尺寸） | AU 规则强制 `warranty_description`，或该 PT 只认 `item_depth_width_height`（US 是 `item_length_width_height`） | 脚本已通用兜底：缺 `warranty_description` 补 "No warranty"；有 `item_depth_width_height` 属性时把 US 的 length→depth 映射（2026-10-20 BASKETBALL_HOOP 实测） |
| 18367 | Amazon 自动把 PT 改成更贴切的类目（WARNING，非失败），该 SKU 的 ASIN 会延迟分配 | 不动，隔天复查；如确属原 PT，需改标题/描述/卖点贴合 |
| 100476 | **AU 的 item_name 超过 75 字符**，原文 `Provide an Item Name that is 75 characters or less to use Item Highlights`（attr=`title_differentiation`）。**是 ERROR，会阻塞出 ASIN** | 脚本已固化 `build_au.trim_au_title()`：先剥尾部括号段（尺寸/规格），仍超长按词边界截到 75。实测边界：74/75 字符通过，77/94 报错。提交后被截断的 SKU 仍会残留该 issue（粘性），但 ASIN 会正常分配且 DISCOVERABLE，不必重建 |
| 5995 | 品牌被锁 | 别乱改 brand，需开 case 解锁 |

## 自动化

| automation | 时间 | 做什么 |
|---|---|---|
| `f17eb5ad-ae25-4c14-b50f-174d8033c636`「每日US新上架同步AU」 | 每日 **20:30** | 依次跑 `run_au.py --store zhangaodi --today` 和 `--store liudongdong --today`，把当天 US 新上架复制到 AU |

> 与 CA 的同步任务（`1267b8ee`，20:00）错开半小时，避免同时抢 SP-API 配额。

## 已知限制与注意事项

- ASIN 由 Amazon 异步分配。**实测：提交当天 `summaries` 可能一直为空，隔天（约 20h）才出 ASIN 和状态**；`GET listing` 返回 issues 为空即算提交成功。
- AU 的 `merchant_shipping_group` 只能让 Amazon 分配，无法预先指定通用模板。
- **不同 PT 的 AU required 不同**，必须按 PT 动态拉 schema 判断（脚本已实现）。实测：
  - `SKIN_CLEANING_BRUSH`：需要 `recommended_browse_nodes`；
  - `APPAREL_GLOVES` / `STORAGE_HOOK` / `COSMETIC_NAIL_SET` / `STORAGE_RACK` / `STRING_LIGHT`：**不需要**；
  - `COSMETIC_NAIL_SET` 的 AU schema **不认 `model_name`**（多填只是 WARNING 90000900，脚本已按 schema 自动剔除）。
- ⚠️ **刘冬冬 AU 有一批历史 listing 存在问题**（实测 483 系列 4 个尺寸子体）：价格未按 AU 公式（如 3mx2m 现价 A$49.49，公式应 A$63.99）、PT 被降级成 `PRODUCT`（US 是 `STRING_LIGHT`）、**且与 US 共用同一 ASIN**（跨市场匹配）。用本 skill 重刷会新建独立 AU SKU，是否覆盖需老板拍板。
- **AU 会把很多 PT 当「电器」审**：只要该 PT 的 AU schema 有 `power_plug_type` / `accepted_voltage_frequency`，即使商品是纯手动工具（手动榨汁器、墙锚枪）也必须填，否则 90220。脚本按 `AU_ELEC_DEFAULTS` 自动补 `no_plug` + `100v_240v_50hz_60hz`；**真实带电插头的商品**要在 `PT_EXTRA` 里按 PT 覆盖成 `type_i_3pin_au` + 对应电压。
- **电池合规三类字段**（`battery_installation_device_type` / `has_multiple_battery_powered_components` / `contains_battery_or_cell`）同样属规则型必填（90220），**只在源 listing 声明含电池时才补**（`AU_BATTERY_DEFAULTS`）：内置锂电（Rechargeable/Cordless/Type-C）→ `not_installed` + `False` + `battery`。**父体不加这三项**（父体加了报 90004205）。
- **`number_of_compartments`** 只对白名单 PT（`AU_COMPARTMENTS_PTS`，目前 `BACKPACK`）补默认 1；其他 PT 不填也能过，乱填是脏数据。
- `batteries_required` 只在 AU schema 真认识该属性时才填（不认识会报 90000900 WARNING）。
- 部分 PT（实测 `AUTO_ACCESSORY`）与 US 共用同一 ASIN（跨市场匹配），AU 建出来会直接复用 US ASIN，属正常。
