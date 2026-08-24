---
version: 1.0.0
name: nexgo-skills-claude-product-system
description: Claude-inspired warm editorial product UI for the NEXGO Skills management system. This design system adapts DESIGN-claude.md into a task-focused Vue product surface: warm cream canvas, coral primary actions, dark product/code panels, restrained card radius, low-shadow elevation, and dense but readable management screens.
source: DESIGN-claude.md
register: product
colors:
  primary: "#cc785c"
  primary-active: "#a9583e"
  primary-disabled: "#e6dfd8"
  ink: "#141413"
  body: "#3d3d3a"
  body-strong: "#252523"
  muted: "#6c6a64"
  muted-soft: "#8e8b82"
  hairline: "#e6dfd8"
  hairline-soft: "#ebe6df"
  canvas: "#faf9f5"
  surface-soft: "#f5f0e8"
  surface-card: "#efe9de"
  surface-cream-strong: "#e8e0d2"
  surface-dark: "#181715"
  surface-dark-elevated: "#252320"
  surface-dark-soft: "#1f1e1b"
  on-primary: "#ffffff"
  on-dark: "#faf9f5"
  on-dark-soft: "#a09d96"
  accent-teal: "#5db8a6"
  accent-amber: "#e8a55a"
  success: "#5db872"
  warning: "#d4a017"
  error: "#c64545"
typography:
  display-xl:
    fontFamily: "Copernicus, Tiempos Headline, Cormorant Garamond, Source Han Serif SC, Noto Serif SC, serif"
    fontSize: 64px
    fontWeight: 400
    lineHeight: 1.05
    letterSpacing: -1.5px
  display-lg:
    fontFamily: "Copernicus, Tiempos Headline, Cormorant Garamond, Source Han Serif SC, Noto Serif SC, serif"
    fontSize: 48px
    fontWeight: 400
    lineHeight: 1.1
    letterSpacing: -1px
  display-md:
    fontFamily: "Copernicus, Tiempos Headline, Cormorant Garamond, Source Han Serif SC, Noto Serif SC, serif"
    fontSize: 36px
    fontWeight: 400
    lineHeight: 1.15
    letterSpacing: -0.5px
  title-lg:
    fontFamily: "StyreneB, Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 22px
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: 0
  title-md:
    fontFamily: "StyreneB, Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 18px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0
  title-sm:
    fontFamily: "StyreneB, Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 16px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0
  body-md:
    fontFamily: "StyreneB, Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0
  body-sm:
    fontFamily: "StyreneB, Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: 0
  caption:
    fontFamily: "StyreneB, Inter, Segoe UI, PingFang SC, Microsoft YaHei, sans-serif"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: 0
  code:
    fontFamily: "JetBrains Mono, Cascadia Code, Consolas, monospace"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: 0
rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  pill: 9999px
spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  section: 72px
components:
  app-shell:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.body}"
    maxWidth: 1200px
  top-nav:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    height: 64px
    rounded: "{rounded.lg}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.caption}"
    rounded: "{rounded.md}"
    height: 40px
  button-secondary:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    borderColor: "{colors.hairline}"
    rounded: "{rounded.md}"
    height: 40px
  search-panel:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: 24px
  skill-card:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: 24px
  detail-panel:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.body}"
    borderColor: "{colors.hairline}"
    rounded: "{rounded.lg}"
    padding: 32px
  workspace-panel:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.body}"
    rounded: "{rounded.lg}"
    padding: 24px
  code-window-card:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    typography: "{typography.code}"
    rounded: "{rounded.lg}"
    padding: 24px
  command-snippet:
    backgroundColor: "{colors.surface-dark}"
    textColor: "{colors.on-dark}"
    typography: "{typography.code}"
    rounded: "{rounded.lg}"
    padding: 18px
  table:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.body}"
    borderColor: "{colors.hairline}"
    rounded: "{rounded.lg}"
  text-input:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    borderColor: "{colors.hairline}"
    rounded: "{rounded.md}"
    height: 40px
  notice:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.body}"
    borderColor: "{colors.hairline}"
    rounded: "{rounded.lg}"
---

# Design

## Overview

NEXGO Skills 的默认场景是内部工程师和管理员在白天办公屏幕前检索、上传、升级和治理 Skill。界面应采用明亮暖画布降低管理后台的紧张感，用珊瑚色只标记主要动作，用深色面板承载安装命令、代码、ZIP 约束和版本记录等产品证据。

该系统参考 `DESIGN-claude.md`，但不是 Claude 营销页复刻。它是产品 UI：信息密度可以更高，组件状态必须完整，动效必须服务反馈，标题可以有编辑气质，表单、标签、按钮和数据区仍以清晰可扫读为先。

## Visual Strategy

色彩策略为 restrained：暖奶油背景占主体，珊瑚色控制在主要按钮、焦点态、关键状态和少量徽标中。深色产品面板用于 `CommandSnippet`、安装命令、Markdown 代码块、版本历史中的技术片段和危险操作确认，不作为整站默认背景。

节奏为 canvas -> cream panel -> dark code/product island -> canvas。避免连续堆叠同一种卡片面；同一屏内先给用户完成任务所需的信息，再给解释性内容。

## Color Usage

- `canvas` 是页面底色，避免纯白和冷灰。
- `surface-soft` 用于搜索区、工具栏、表单区等轻分组。
- `surface-card` 用于 Skill 卡片、来源标签组和短内容卡。
- `surface-dark` 用于安装命令、代码、终端式反馈和高风险确认。
- `primary` 只用于主要 CTA、选中态、焦点环和关键链接，不做装饰铺色。
- `muted` 可用于辅助文本；占位文本必须使用 `muted` 或更深色，不使用 `muted-soft`。

正文 `body` 在 `canvas` 上必须保持 4.5:1 以上对比度。深色面板内正文使用 `on-dark`，辅助标签使用 `on-dark-soft`，不要把普通灰字直接放在深色或珊瑚面上。

## Typography

展示标题可使用 Copernicus / Tiempos / Cormorant Garamond / 中文宋体系后备，保持 400 字重和轻微负字距，主要用于首页标题、详情页标题和空状态标题。产品标签、按钮、表单、表格、导航和卡片元信息使用 StyreneB / Inter / 系统中文黑体系。

产品界面不使用夸张流体字号。一级标题建议 32-40px，二级标题 24-30px，管理面板标题 18-22px。长正文限制在 65-75ch，Markdown 描述需要 `text-wrap: pretty`；h1-h3 使用 `text-wrap: balance`。

## Layout

内容最大宽度约 1200px。公开首页以搜索和来源切换为第一任务，随后展示本地库或 `skills.sh` 列表。工作台以标签页或侧栏组织 Skill、分组和用户管理，表单和表格保持任务密度，不做营销式大 hero。

使用 Grid 处理卡片、表格和双栏表单，使用 Flex 处理导航、按钮组、标签和元信息。卡片半径不超过 12px，较大容器不超过 16px；不要在卡片内再嵌套卡片。

## Components

### Navigation

`SiteHeader` 保持稳定入口：品牌、首页、使用教程、登录/用户中心。激活态使用 `surface-card` 或浅珊瑚背景，文字用 `ink`，不要使用全大写宽字距作为默认导航风格。

### Search Panel

公开首页的搜索面板是主要工作入口。它应包含来源切换、当前来源说明、搜索框和结果计数。搜索框焦点态使用珊瑚色边框和低透明焦点环，清空按钮为次要按钮。

### Skill Card

Skill 卡展示来源、名称、版本、描述摘要和下一步动作。背景使用 `surface-card`，无需大阴影；hover 可轻微改变背景或边框。来源标签要清楚地区分本地库和外部源，本地可管理、外部只读的边界不能靠颜色猜测。

### Detail Modal / Detail Page

详情区优先展示描述、版本、贡献者、来源和下载地址。本地 Skill 展示安装命令，命令片段使用深色 `command-snippet` 且复制反馈要明确；`skills.sh` Skill 不展示本地 CLI 命令，只提供前往官方详情页查看安装方式的入口。Markdown 内容保持可读行长，代码块允许横向滚动而不强行换行。

### Workspace Panels

工作台面板用于 Skill 管理、组管理和用户管理。面板采用 `surface-soft` 或 `canvas`，表单控件统一 40px 高度、8px 半径。危险动作使用文本清晰的确认区，颜色只作为辅助，不单独承担语义。

### Tables And Lists

表格用于版本、用户和分组数据。表头保持轻底色，行 hover 仅轻微强调。状态芯片使用低饱和背景和明确文字，不使用大面积高饱和色。

### Notices

通知以简洁标题和下一步说明为主。错误信息要说明失败原因和用户可尝试的动作；成功信息要短，不打断主流程。

## Motion

常规交互使用 150-220ms ease-out。允许按钮、卡片 hover、弹窗进入、toast 出现和列表加载状态过渡。不要做整页入场编排。所有动效必须在 `prefers-reduced-motion: reduce` 下关闭位移和长过渡。

## Responsive Behavior

小屏下导航可折叠为紧凑顶部区，搜索面板变为单列，Skill 卡片一列展示，详情弹窗应使用接近全屏的滚动面板。代码和命令保持等宽字体并允许横向滚动。管理表格在移动端优先改为行块或关键字段摘要，不压缩到不可读。

## Do's

- 使用暖奶油画布作为默认页面气氛。
- 用珊瑚色表达主要动作、焦点和当前选择。
- 用深色产品面板承载命令、代码和高确定性技术内容。
- 让本地库、外部源、权限范围和删除状态在文案和结构上都清楚。
- 保持按钮、输入框、标签、表格和弹窗的状态词汇一致。

## Don'ts

- 不要使用冷蓝灰或 Spotify 绿色作为主身份。
- 不要把整个产品做成深色霓虹界面。
- 不要给卡片同时加 1px 边框和大软阴影。
- 不要使用 24px 以上卡片圆角。
- 不要把每个区块都加小号大写 eyebrow 或编号标记。
- 不要用装饰性渐变文字、玻璃拟态或手绘 SVG 作为视觉主张。

## Known Gaps

当前 `frontend/src/assets/main.css` 仍包含旧的蓝色玻璃风格和后置的深色绿色覆写。本文档定义后续 `$impeccable` 工作应遵循的目标设计方向；真正落地时应通过 `$impeccable polish` 或 `$impeccable colorize` 统一 CSS token，而不是继续叠加第三套主题。
