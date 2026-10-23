# 项目长期记忆（US→AU 跨站复制）

## 站点/身份铁律（勿改）
- 张奥迪 AU seller = `A36XI3SU3OR6IQ`；刘冬冬 AU seller = `A2U23KQN97ZU0T`。
- 凭证文件第 0 个 refresh_token = AU，第 1 个 = NA。
- AU marketplace `A39IBJ37TRP1C6`，端点 `sellingpartnerapi-fe.amazon.com`。
- 价格公式（2026-10-16 定版）：AU 报价 = (US 价 + 5.99) × 1.43 − 12.99 → .99；划线价 = 报价 × 1.7；AUD。

## AU 字段陷阱（新增，逐条踩过）
- **4000004：US PT=通用 `PRODUCT` 时 AU 不许建品** → `build_au.PT_OVERRIDE`（US SKU→AU PT）+ `_probe_pt.py` 反查真实 PT。**仅当 US 仍为 PRODUCT 才覆盖**：Amazon 会异步重分类（10-22 水龙头罩 PRODUCT→FAUCET），那时以 Amazon 为准。
- **90220 电池三字段**：内置锂电商品必须给 `battery_installation_device_type` / `has_multiple_battery_powered_components` / `contains_battery_or_cell`。**`installed_in_equipment` 会被 90004205 否掉，一律用 `not_installed`**。父体不要加（加了自己也 INVALID）。
- **90220 `number_of_compartments`**：仅 BACKPACK 需要，白名单 `AU_COMPARTMENTS_PTS` 补 1；别全 PT 通用补。
- **18027 = 主图含文字/水印被压制**（ASIN 已分配但 status 为空），需换主图，脚本修不了。
- `list_price` 必须 `value_with_tax`（缺→99022）；`purchasable_offer` 不带 `quantity`（→90000900）；`merchant_shipping_group` 去掉（→90244）；`language_tag`=`en_AU`（→100720）。
- **父体 patch 绝不能带 US 的 `purchasable_offer` / `list_price` / `merchant_shipping_group` / `fulfillment_availability`** —— 会把 USD 价格与 US 运费模板 UUID 带过去，直接 99022 / 90244。`build_au.build` 已修。
- **独立项（US catalog 无父子关系）按 US `parentage_level` 建**：父→AU 父体、子→AU 可售单 SKU（`parent_sku_au=None`，不写 parentage_level / variation_theme）。`run_au.upload_group` 已加分支。
- **90220 = AU 规则型必填字段缺失**（不在 schema `required` 里，脚本无法预判），已实测：
  - PET_APPAREL / FOOD_SLICER 等：`warranty_description`（本店 US 侧默认值写作 `NAN`）。
  - TOOLS：`power_plug_type` + `accepted_voltage_frequency`（焊接电极夹这类非电器也会被类目规则要求，属误判）。
  - FOOD_SLICER：`number_of_items` + `care_instructions` + `item_length_width_height`。
  - **AU 把「非电器」判成电器是普遍现象**（JUICER 手动榨汁器、AUTO_ACCESSORY 墙锚枪都中招）→ 已做成通用兜底 `AU_ELEC_DEFAULTS`（no_plug + 100v_240v_50hz_60hz），不再逐 PT 硬编码。
- **100521 = Amazon 例行审核**（≤48h，原文「otherwise the listing will be published」），不是失败，别当 ERROR 去改字段。
- **100336 = 尺寸低于 AU 类目下限，只是 WARNING**，不阻塞上架。
- **100476 = AU `item_name` 超 75 字符**（原文「Provide an Item Name that is 75 characters or less to use Item Highlights」，attr=`title_differentiation`）。**是 ERROR，会卡住 ASIN 分配**。实测边界 74/75 通过、77/94 报错。`build_au.trim_au_title()` 已固化：先剥尾部括号段（尺寸规格），再按词边界截断。提交后被截断的 SKU 仍残留该 issue（粘性），但 ASIN 正常分配、DISCOVERABLE，**不必 DELETE 重建**。
- `batteries_required` 必须按 au_props 白名单填，AU 不认识的 PT 填了会报 90000900 WARNING 噪音。
- **8560 + 13013 中招 PT：`APPENDAGE_WARMER`（电热手套，4 子体）、`SLEEPING_BAG`、`HOLE_PUNCH`（2026-10-22）** → 必须真实 UPC，卡在老板侧。
- `AUTO_ACCESSORY` 等 PT 会与 US 共用同一 ASIN（跨市场匹配），AU 建出来直接复用 US ASIN，属正常。

## browse node 取法（升级）
- **首选**：AU 竞品 ASIN → `_node_from_asin.py` 走 Catalog Items `classifications`，最内层 `classificationId` 即 node。AU 前台多数 listing 不显示 BSR，翻前台不可靠。
- 已录入：SKIN_CLEANING_BRUSH=5150180051、DECORATIVE_SIGNAGE=10331504051、APPENDAGE_WARMER=5047994051（Skiing>Men>Gloves）、HOLE_PUNCH=5269423051（Paper & Paper Crafts>Punches）、FUNNEL=5016687051（暂唯一真必填 node）。备用：GARLAND=4976017051、PET_TOY=5848095051、PET_APPAREL=5265199051、STORAGE_COVER=5707689051。
- **`_probe_pt.py <店> <US SKU>` 一次拿全「真实 PT + node」**（AU 搜同款竞品 → productTypes / classifications 最内层），比翻前台快，US PT=PRODUCT 时必用。

## 运维
- US 新建的变体家族，`catalog/relationships` 可能滞后返回空（HTTP 200 但 variations=[]），导致被误判独立项；次日会同族挂靠，重跑即可。
- 失败 SKU 若为 404（未创建），修正后可直接重传，无「粘性 issues」问题。
- 复验工具：`scripts/_verify.py --store <店> SKU1 SKU2 ...`（**必须带 --store**，硬编码默认 zhangaodi 时会全返 404 误判）。**且必须传 AU SKU 名**：刘冬冬规则为 -US/-us→-AU，无 -US 后缀的 SKU 直接追加 `-AU`（WN-UF7Y-Z1E6 → WN-UF7Y-Z1E6-AU），传 US SKU 会全 404 误判。
- 补跑工具：`scripts/_rerun.py <店> <US父SKU> <子SKU逗号列表>`。
