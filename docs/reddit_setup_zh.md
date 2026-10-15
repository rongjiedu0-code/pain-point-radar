# Reddit 接入：当前缺项与配置

截至2026-10-15：代码已补充官方 OAuth 适配器和独立验收模式；没有 API 访问批准与凭据，尚不能证明真实 Reddit 采集恢复。HN 成功不作为 Reddit 验收通过。

## 你现在需要准备什么
1. 确认自己的 Reddit 账号用户名。
2. 从[官方 Data API 文档](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki)进入[访问申请](https://support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=14868593862164)。以真实用途申请，说明是否用于产品需求研究或商业用途；不能把本项目虚构成学术研究。表单要求优先考虑 Devvit，不适用时说明为何需要外部 Python/GitHub Actions。
3. 获准后，按 Reddit 指引创建允许该用途的 OAuth 应用，获取 client_id 与 client_secret。拥有应用不等同于 API 访问获批；本代码适配 confidential client 的 app-only client_credentials，或既有授权的 refresh_token，不接收账号密码。
4. 将凭据配置到仓库，不发到聊天、不提交代码：

在[Actions Secrets](https://github.com/rongjiedu0-code/pain-point-radar/settings/secrets/actions)添加：
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_REFRESH_TOKEN`：仅当批准的应用需要用户授权、且已取得 refresh token 时配置；app-only 模式不需要。

在[Actions Variables](https://github.com/rongjiedu0-code/pain-point-radar/settings/variables/actions)添加：
- `REDDIT_API_APPROVED=true`：仅在已获得官方许可后设置。这只是用户配置开关，不会替你申请或验证批准。
- `REDDIT_USER_AGENT=linux:pain-point-radar:v3.2 (by /u/你的Reddit用户名)`：替换为真实用户名。

## 如何单独验收 Reddit
在 Actions 手动运行时选 `run_mode=reddit-check`，选择已包含本次修复的分支。也可在本地设置同名环境变量后运行：

```text
python pain_point_radar_v3_anti_block.py --check-reddit --subreddits SaaS,smallbusiness,SideProject
```

该模式不查询 HN，不更新 CSV/seen-state。三个社区都能从官方 API 得到合法 Listing 才返回0；没有匹配痛点不代表接口失败。检查诊断 JSON 中各社区的 `status=ok` 与请求 `http_status=200`；只有拿到真实返回才能确认接通。

正式扫描若必须要求 Reddit 完整可用，使用 `--require-reddit`，避免 HN 回退让整个任务看起来通过。

状态含义：
- `approval_required`：未配置批准开关；不会向 Reddit 发请求。
- `credentials_missing`：缺 client_id / client_secret。
- `user_agent_missing_or_invalid`：缺可识别的应用和用户名。
- `authentication_failed`：token 交换失败、凭据无效或重新认证后仍401。
- `access_denied`：官方接口403；需核对批准范围、应用权限及社区访问权限，不能靠换参数保证解决。
- `rate_limited`：收到429或额度耗尽；本轮不再请求其他社区，遵守服务器等待窗口。
- `listing_failed`：网络/响应结构等问题，查脱敏诊断。

默认实时采集已从匿名 JSON/RSS/归档链路切换到官方 OAuth；旧解析 helper 保留用于回归测试，不作为未配置凭据时的绕行路径。

## 可用于申请的真实项目说明草稿

以下需要本人核对后填写，不是自动提交：

```text
Subject: Request for read-only Data API access for Pain Point Radar

Reddit username: [your actual username]
Source code: https://github.com/rongjiedu0-code/pain-point-radar

I am building an open-source Python prototype to identify explicit software
workflow problems in public discussions in r/SaaS, r/smallbusiness and
r/SideProject. The requested access is read-only: up to 20 newest submissions
per community in one scheduled daily run, plus limited manual verification.
No posting, voting, messaging, or private community access is requested.

The intended use includes software product-idea research. Please advise on
eligibility and any commercial-use approval or licensing requirements for
this use case. I do not claim academic research status for this project.

The prototype currently runs externally in Python/GitHub Actions and exports
candidate records for manual review. Please advise whether Devvit can support
this use case or whether external Data API approval is appropriate.

Data storage, retention, deletion handling and distribution plans:
[describe the actual approved plan before submitting; current repo uses public
CSV/Actions artifacts, which must not be assumed acceptable for Reddit content]
```

官方要求处理被删内容，旧仓库的公开 Git 历史/Actions 产物不适合作为默认长期保存 Reddit 正文的方案。获批后首次启用真实采集前，还需根据批准范围确定私有存储、保留期与删除同步；不能直接把未核对的承诺写入申请。本次无凭据运行没有新增任何 Reddit 内容。

参考：[官方 OAuth 技术说明](https://github.com/reddit-archive/reddit/wiki/OAuth2)、[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)。旧技术 Wiki 不代表当前准入政策，能换取 token 也不等同于用途已获批准。
