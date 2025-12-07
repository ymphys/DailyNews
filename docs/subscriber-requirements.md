# 订阅者所需信息

DailyNews 会按你提供的偏好给你发送定制化的新闻 digest。请把下面这些信息发给维护者（例如创建一个 GitHub issue 或直接发邮件），我们会把你添加到订阅列表中并在测试完成后开始投放。

## 你需要提供的信息

- `id`：一个英文小写的短标识，例如 `alice`，方便我们在运行日志和状态中识别你。
- `email`：接受邮件的邮箱地址
- `digests`：希望接收的主题 digest 列表，至少填写一个，例如 头条新闻、 AI新闻等。
- `frequency`：期望接收频率，比如 每天 或 每两天，目前默认以 每天 作为发送节奏。
- `send_time`：你希望收到摘要的本地时间（24 小时制，比如 `08:00`），用于记录你的偏好。
- `timezone`：常用时区名称（如 `Asia/Shanghai`、`UTC`），配合 `send_time` 说明你的本地时间。

如果你还有特殊需求（比如某天希望暂停、想帮忙做测试等），一并写在消息里，我们会在操作时额外留意。

## 当前可选的 digest

目前项目维护的 digest 包括（但不限于）：

- `global_headlines`：全球主要区域的头条集合。
- `china_economy`：聚焦中国政经趋势的主题摘要。
- `ai`：涵盖中英文人工智能与大模型动向。
- `physics`：涵盖与物理/物理学家有关的新闻。
- `entertainment`：娱乐影音与影视热点。

如果你想关注的主题尚未列出，可以在提交表单时提一句，我们会评估是否新增或调整相关 digest。

## 参考格式

你可以按下面这种结构发送信息：

```
id: zjb
name: 张嘉宝
email: 1047962614@qq.com
digests: [global_headlines, ai]
frequency: daily
send_time: 08:00
timezone: Asia/Shanghai
```

这只是演示，具体内容请根据你自己的需求填写。
