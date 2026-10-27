# RTX PRO 5500 全网情报核对任务（云端每日执行）

你在仓库 gaaiyun/gpu-5500-brief 的云端副本里工作。任务：搜索过去 72 小时内关于 NVIDIA RTX PRO 5500（84GB 工作站卡）在中国大陆的价格、订单、配额、审批、交付、渠道货况的信息，读原文核对后更新 `data/feed.json`，推送到分支 `claude/intel-feed`。网站每日构建会读取这个分支上的文件，钉钉/微信日报会直接引用。

## 1. 准备

```bash
git fetch origin
git checkout claude/intel-feed 2>/dev/null || git checkout -b claude/intel-feed origin/main
git merge --no-edit -X theirs origin/main
# main 上的 feed.json 已合并前一天的云端结果和每日 CI 检索结果，是最新全集，从它开始改。
git checkout origin/main -- data/feed.json
```

每日 CI 另有一轮自动检索（scripts/sweep.py，用便宜模型起草、代码核对数字），结果写在 main 的 data/feed.json 里，`sweep` 字段记录了它读过什么、跳过了什么。你的任务是在它之上做更深的核对：它只能读到少数站点的正文，公众号只能留成线索；你能读到的，就把线索升级成条目。

先读：`data/feed.json`（已有条目，避免重复）、`data/evidence.json`（已核验的核心来源，避免重复）、`git show origin/main:data/inbox.txt`（人工转来的链接，最优先处理）、`scripts/feed.py`（字段校验规则，必须遵守）。

## 2. 搜索面（每轮都覆盖，中英文都搜）

- 主流财经与科技媒体：路透、彭博、The Information、FT、WSJ、日经、CNBC、财联社、第一财经、证券时报、21世纪经济报道、界面、澎湃、财新、经济观察报。
- 行业媒体与研究：TrendForce/集邦、DIGITIMES、雷峰网、集微、36氪、电子工程专辑、Tom's Hardware、VideoCardz。
- 公众号：通过搜索引擎找它在腾讯新闻、搜狐号、网易号、百家号、新浪看点等平台的镜像；`site:mp.weixin.qq.com` 也要搜。
- 搜狗微信搜索（公众号的主要入口）：用 WebFetch 打开 `https://weixin.sogou.com/weixin?type=2&query=关键词`（每轮最多 3 个关键词，例如 `RTX PRO 5500`、`RTX PRO 5500 报价`、`RTX PRO 5500 到货`）。结果页里的 `/link?url=` 跳转链接对程序会转到验证码页，**不要打开、不要尝试通过验证码**。只记录结果页上的标题、公众号名、摘要，作为线索写入 `leads`；然后用文章标题原文去普通搜索引擎找它在腾讯新闻、搜狐、网易、百家号、新浪等平台的镜像全文，读到正文的再按第 3 节规则升级为 C 级快讯条目。结果页本身出现验证码就停止搜狗部分。
- 社媒与社区：微博、知乎、小红书、雪球、什么值得买、X、Reddit。
- 渠道挂价：京东/淘宝/闲鱼/华强北报价、宽泛采销等撮合平台。只记录读到的挂价原文，不推断成交价。

每轮至少执行 12 次搜索，上面每一类至少 2 次，中英文都要有。搜索结果里每个看起来有新信息的链接都要用 WebFetch 打开读正文。抓取失败（DNS 失败、403、验证码）的链接记下来，在汇报里如实列出，不要写成“已覆盖”。

关键词组合示例：`RTX PRO 5500 报价`、`RTX PRO 5500 到货`、`RTX PRO 5500 配额`、`RTX PRO 5500 工信部`、`RTX PRO 5500 样卡`、`"RTX PRO 5500" China price`、`"RTX PRO 5500" shipments`。排除同名的 SSD、显示器、手机等无关 5500 产品。

## 3. 核对规则（硬约束）

1. 只收录你真正打开并读到正文的内容。读不到正文的，或只有标题的，一律不收。遇到验证码、登录墙、反爬拦截就跳过，不要绕过。
2. 每条情报回答三件事：发生了什么（summary）、对大陆报价或交付有什么影响（impact）、下一步核实什么（watch）。来源名和标题不能代替内容。
3. 数字照抄原文，保留“约”“可能”“据称”“预计”这类限定词，并写清楚是谁说的（具名人士 / 匿名知情人士 / 媒体推算）。不得自行换算出新的价格或数量写进 summary。
4. 追溯原始出处：转载文章找到最早的原始报道，用原始报道作 url；转载方放进 corroboration（必须是 https 链接）。
5. 可信度分级：
   - A「多方印证」：至少两个独立来源一致，且其中至少一个是具名人士、官方或公告。必须附 corroboration。
   - B「单一可信来源」：主流或行业媒体的原创报道，即使依赖匿名信源。
   - C「待核实线索」：公众号、社媒、论坛、单一渠道挂价。
6. 公众号和社媒（source_type 为“公众号”或“社媒”）只能是 C 级，而且必须带 claims：把文章里与价格、订单、交付、政策有关的说法逐条拆开（最多 6 条），每条标注 status：
   - “有出处”：能找到原始报道，ref 填原始报道链接；
   - “推算”：作者自己算出来或推断的；
   - “无出处”：找不到任何来源；
   - “与出处不符”：原始报道说法不同或被夸大，例如把匿名信源写成“坐实”，ref 填原始报道链接。
   这类内容的价值是及时、信息量大，核对结果要让读者一眼看出哪些可信。
7. 已在 feed.json 或 evidence.json 中的同一事件不重复收录。新报道只是转述旧消息的，只把链接加进原条目的 corroboration。
8. 新事实推翻旧条目时，在旧条目的 watch 里写明“已被 xxx 更新”，并新增条目。

## 4. 写入 data/feed.json

保持 `schema_version: 1`。更新 `updated_at`（北京时间 ISO 格式，带 +08:00）、`agent: "cloud-routine"`、`searched`（本轮实际执行过的搜索词原文列表，不超过 30 条；没搜过的不能写）。`items` 每条字段：

```json
{"id": "来源-日期-简短英文", "title": "≤60字", "published_at": "YYYY-MM-DD（原文发布日期，不是采集日期）",
 "publisher": "≤60字", "source_type": "官方|公告|主流媒体|行业媒体|研究机构|公众号|社媒|电商/渠道",
 "url": "https://原始出处", "grade": "A|B|C", "summary": "≤260字", "impact": "≤140字", "watch": "≤60字",
 "corroboration": ["https://..."], "claims": [{"text": "≤80字", "status": "有出处|推算|无出处|与出处不符", "ref": "https://..."}],
 "checked_at": "YYYY-MM-DD"}
```

保留发布日期在 45 天以内的条目，总数不超过 12 条，新的在前。文本里不要出现 HTML 标签。

另有顶层数组 `leads`（未核实线索，最多 15 条，只给链接供人点开自己判断，不进日报图）：读不到正文、或可信度不够但与价格/交付/配额相关的内容放这里，不要硬升级成条目。

```json
{"title": "文章原标题，≤80字", "publisher": "公众号或账号名", "source_type": "公众号|社媒|电商/渠道|行业媒体|主流媒体|其他",
 "url": "https://...", "published_at": "YYYY-MM-DD 或空字符串", "found_via": "搜狗微信|微博|知乎|...", "snippet": "结果页摘要原文，≤160字"}
```

搜狗来的线索，url 用按标题搜索的地址：`https://weixin.sogou.com/weixin?type=2&query=` 加 URL 编码后的完整标题（人在浏览器里点开就能找到原文）；如果找到了 mp.weixin.qq.com 或镜像的直接链接，就用直接链接。同一标题只留一条，已经升级为条目的线索从 leads 里删掉，超过 14 天的线索删掉。

只有 A/B 级条目会进日报图；C 级快讯和 leads 只出现在网站和推送文字里。

处理完 inbox 里的链接后，不需要修改 inbox.txt（它在 main 分支上，由人工维护）。

## 5. 校验并推送

```bash
python -c "import json,sys; sys.path.insert(0,'scripts'); from datetime import date; from feed import load_feed; items,bad=load_feed(json.load(open('data/feed.json',encoding='utf-8')), date.today()); print(len(items),'ok'); print(bad); sys.exit(1 if bad else 0)"
python -m unittest tests.test_feed
git add data/feed.json
git commit -m "chore(情报): 全网情报核对 $(TZ=Asia/Shanghai date +%F)"
git push origin claude/intel-feed
```

校验报错就修正对应条目再提交。只改 `data/feed.json`，不改其他文件，不推 main，不 force push。提交信息不加任何 AI 署名行。

## 6. 结束时汇报

用几行中文写清：本轮实际搜索次数和各类来源的搜索次数、打开读到正文的链接数、抓取失败的链接数，新增几条（各等级几条）、处理了哪些 inbox 链接、跳过了哪些（原因：读不到正文、无关、重复）。没有新内容也照常更新 updated_at 并推送，说明“本轮无新增”。
