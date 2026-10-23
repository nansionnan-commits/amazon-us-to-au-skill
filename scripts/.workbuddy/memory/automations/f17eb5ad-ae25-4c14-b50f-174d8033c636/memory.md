# automation f17eb5ad「每日US新上架同步AU」执行记录

## 2026-10-16 20:30
- 刘冬冬：当天无 US 新上架。
- 张奥迪：31 ASIN / 11 组 → AU 成功 8 / 失败 21 / 跳过 2。
- 失败主因：全新错误码 90220（AU 规则型必填缺失），源 US listing 无该数据：
  - PET_APPAREL 缺 warranty_description；TOOLS 缺 power_plug_type + accepted_voltage_frequency；FOOD_SLICER 缺 number_of_items / care_instructions / item_length_width_height。
- 跳过：DECORATIVE_SIGNAGE 缺 AU browse node。
- 修复了脚本 3 处结构缺陷（父体字段泄漏 99022/90244、独立项一律当父体建），价格公式未动；补跑 8 个独立项后 6 个成功。
- 报告：scripts/US到AU同步报告_2026-10-16.md

## 2026-10-17 20:30
- 张奥迪 9 ASIN / 2 组：5 个 AU SKU 可售；电热手套 4 子体卡 8560+13013（APPENDAGE_WARMER 必须真实 UPC，等老板申请豁免/给 UPC）。
- 刘冬冬 8 ASIN / 4 组：4 个 AU SKU 可售；2 组打孔器 4 个 SKU 卡 100521（Amazon 例行审核 ≤48h，非失败，明日复查）。
- 修脚本：补 2 个 browse node（APPENDAGE_WARMER / HOLE_PUNCH）；新增 AU_ELEC_DEFAULTS 电气必填兜底（修 JUICER、AUTO_ACCESSORY 的 90220）；batteries_required 改白名单；PUT issues 改为全量打印；_verify.py 加 --store。
- 新增工具：_node_from_asin.py（竞品 ASIN 反查 node）、_rerun.py（按 US SKU 补跑）、_diag.py、_find_node.py。
- 报告：scripts/US到AU同步报告_2026-10-17.md

## 2026-10-18 20:30
- 两店当天（UTC）均 0 个 US 新上架，无上传；`_today_probe.py` 交叉核对确认非过滤失效（最近一条均为 10-17）。
- 复查昨日：刘冬冬 4 个 HOLE_PUNCH SKU（100521）已全部 DISCOVERABLE/BUYABLE，ASIN 分配完成 → 100521 确认纯等待。
- 张奥迪 APPENDAGE_WARMER 4 子体仍 8560+13013，等老板 GTIN 豁免/UPC（父体已在售但无法选规格）。
- 修脚本 4 处：auth/auth_au 请求加重试（首跑因 read timeout 崩溃致全天归零）；fetch_today_asins 非 200 改抛错（此前静默当成 0 个，会漏跑一整天）；0 个时短路省配额；新增 `_today_probe.py` 诊断工具。
- 报告：scripts/US到AU同步报告_2026-10-18.md

## 2026-10-20 20:30（实跑 15:20）
- 张奥迪 11 ASIN / 3 组（ANIMAL_SHELTER、DRINKING_CUP、BASKETBALL_HOOP）→ 11 AU SKU，10 个 ASIN 已出且 DISCOVERABLE，1 个（LC-33XG-6NWH-AU）待 ASIN；0 失败。
- 刘冬冬当天 0 个 US 新上架（probe 交叉核对：最近一条 10-07）。
- 新踩坑：BASKETBALL_HOOP 5 子体 90220 = 缺 warranty_description + AU 只认 item_depth_width_height（US 是 item_length_width_height）。已在 build_au.py 固化通用兜底（保修补 No warranty、length→depth 映射），补跑全通过。
- 新错误码 18367（WARNING）：Amazon 自动改 PT（BASKETBALL_HOOP→LAUNDRY_HAMPER），非失败，ASIN 延迟；已写入 SKILL.md 速查表。
- 报告：scripts/US到AU同步报告_2026-10-20.md

## 2026-10-20 20:30（同日第二轮）
- 张奥迪当天累计 21 ASIN / 6 组 → 21 个 AU SKU **全部出 ASIN + DISCOVERABLE**，9 个 BUYABLE，0 失败。
- 刘冬冬 0 个（probe 复核通过）。
- 新错误码 **100476 = AU 标题超 75 字符**（ERROR，卡 ASIN）。已在 build_au.py 加 `trim_au_title()` 固化；截断后补跑 4 个 SKU 全部通过。残留 issue 粘性、不阻塞。
- 报告已重写为全天合并版。

## 2026-10-21 20:30
- 两店 UTC 当天均 0 个 US 新上架，无 AU 上传；probe 交叉核对通过（张奥迪最近 10-20T10:21Z，刘冬冬最近 10-17T09:39Z）。
- 复查遗留：张奥迪 LC-33XG-6NWH-AU（原 18367 延迟）ASIN 已出、BUYABLE；APPENDAGE_WARMER 4 子体仍 8560+13013（等老板 UPC/豁免，10-17 挂起至今）。刘冬冬 8 个抽查 SKU 全 DISCOVERABLE。
- 新记提醒：`_verify.py` 查刘冬冬须用 AU SKU 全名（无 -US 后缀的会追加 -AU），否则全 404。
- 报告：scripts/US到AU同步报告_2026-10-21.md


