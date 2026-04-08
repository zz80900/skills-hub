# AD Kerberos + LDAP 开发文档

## 1. 文档目标

本文档用于沉淀后续 `Python` 版本应采用的生产版推荐流程。当前 `Java` 版本仍然是测试实现，但 Python 重构时不应继续照搬“用户自己做 LDAP bind”的方式。

目标不是解释某个语言特性，而是固定以下内容：

- 输入参数和默认值
- Kerberos 认证流程
- LDAP 查询流程
- 姓名解析规则
- 标准输出契约
- 错误处理规则
- Python 重构时建议保留的模块边界

当前实现源码入口：

- [KerberosAdVerifier.java](/E:/code_ai/ad-test/src/main/java/com/xgd/adtest/KerberosAdVerifier.java#L42)

## 2. 生产版业务目标

程序当前只做一件事：给定一个 AD 域账号和密码，验证该账号是否能通过 Kerberos 认证，并在认证成功后通过 LDAP 查询该账号的用户信息。

完成标准：

- Kerberos 登录成功
- 能拿到 Kerberos principal
- 能通过 LDAP 找到对应 AD 用户
- 能输出姓名类字段和全部非空 LDAP 属性

生产版身份边界：

- 待验证账号：只负责 Kerberos 认证
- LDAP 服务账号：只负责目录查询

推荐原因：

- LDAP 查询权限更稳定
- 不依赖每个普通用户都具备相同的目录读取权限
- 后续扩展部门、岗位、组织树、群组等查询时更容易统一治理
- 可以单独给服务账号配置最小只读权限

## 3. 默认环境配置

当前默认配置如下：

- `realm`: `XGD.COM`
- `kdc`: `10.19.8.248`
- `ldapUrl`: `ldap://10.19.8.248:389`
- `baseDn`: `OU=新国都集团|OU=支付硬件事业群|OU=技术中心`
- 默认 principal：`ssc-skills@XGD.COM`

生产版新增推荐配置：

- `ldapBindUsername`：LDAP 服务账号
- `ldapBindPassword`：LDAP 服务账号密码
- `ldapBindPrincipal`：可选，若目录侧要求 UPN 绑定则使用该值

说明：

- `ldapBindUsername` 和待验证用户不是同一个概念
- 待验证用户用于 Kerberos
- 服务账号用于 LDAP bind 和目录查询
- 如果只有一个服务账号，也可以先用该账号作为过渡方案，但 Python 重构时建议把“待验证用户”和“服务账号”明确拆开

说明：

- `baseDn` 支持简写路径格式，程序会自动转换成标准 DN
- 简写 `OU=新国都集团|OU=支付硬件事业群|OU=技术中心`
- 会被转换为 `OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com`

## 4. 输入参数与优先级

当前支持的 CLI 参数：

- `--principal`
- `--username`
- `--password`
- `--realm`
- `--kdc`
- `--ldap-url`
- `--base-dn`
- `--ldap-bind-username`
- `--ldap-bind-password`
- `--ldap-bind-principal`
- `--debug`
- `--help`

当前支持的环境变量：

- `KERBEROS_PASSWORD`
- `AD_TEST_PASSWORD`
- `AD_TEST_PRINCIPAL`
- `AD_TEST_USERNAME`
- `AD_TEST_REALM`
- `AD_TEST_KDC`
- `AD_TEST_LDAP_URL`
- `AD_TEST_BASE_DN`
- `AD_LDAP_BIND_USERNAME`
- `AD_LDAP_BIND_PASSWORD`
- `AD_LDAP_BIND_PRINCIPAL`

参数优先级规则：

1. CLI 参数优先
2. 环境变量次之
3. 最后回退到内置默认值

账号输入规则：

- `--principal` 支持完整 principal，例如 `ssc-skills@XGD.COM`
- `--username` 支持三种格式：
- `ssc-skills`
- `ssc-skills@XGD.COM`
- `XGD\ssc-skills`

principal 归一化规则：

- 如果传入 `DOMAIN\user`，程序只取 `user`
- 如果没有 `@REALM`，程序自动补上当前 realm
- realm 统一转成大写

密码规则：

- 运行时必须有密码
- 密码缺失时直接返回参数错误，退出码 `2`

生产版密码边界：

- `--password` / `AD_TEST_PASSWORD`：待验证用户密码
- `--ldap-bind-password` / `AD_LDAP_BIND_PASSWORD`：LDAP 服务账号密码
- 两者不能混用

## 5. 核心业务流程

### 5.1 总流程

1. 读取参数并完成归一化
2. 设置 Kerberos 运行参数
3. 使用待验证账号密码执行 Kerberos 登录
4. 登录成功后，从 `Subject` 中取 principal 和票据数
5. 使用 LDAP 服务账号做 LDAP simple bind
6. 按搜索根查找“待验证用户”对应的 AD 用户对象
7. 解析姓名字段
8. 打印结构化结果和全部非空 LDAP 属性

### 5.2 Kerberos 流程

Kerberos 相关行为：

- 设置 `java.security.krb5.realm`
- 设置 `java.security.krb5.kdc`
- 设置 `javax.security.auth.useSubjectCredsOnly=false`
- 设置 `sun.security.krb5.disableReferrals=true`
- `debug=true` 时开启 `sun.security.krb5.debug=true`

登录方式：

- 使用 `JAAS + Krb5LoginModule`
- 不使用 ticket cache
- 使用账号密码主动发起认证

成功后输出：

- `kerberos login success`
- `principal`
- `ticket count`

### 5.3 LDAP 绑定流程

LDAP 不复用 Kerberos ticket，而是使用 simple bind。

生产版推荐规则：

1. Kerberos 只验证待验证用户
2. LDAP 永远优先使用固定服务账号绑定
3. 绑定成功后，再去搜索待验证用户对象

服务账号绑定名建议按顺序支持以下格式：

1. `ldapBindPrincipal`
2. `ldapBindUsername@REALM`
3. `NETBIOS\ldapBindUsername`

任一绑定成功即可继续查询；前一个失败不会立即终止。

不推荐的旧方式：

- 用待验证用户自己的账号再做一次 LDAP bind

保留这个旧方式的唯一理由：

- 作为测试或应急回退模式

但 Python 生产版默认行为不应采用它。

### 5.4 LDAP 搜索流程

搜索过滤条件固定为：

```text
(&(objectCategory=person)(objectClass=user)(|(userPrincipalName={principal})(sAMAccountName={accountName})))
```

搜索范围：

- `SUBTREE_SCOPE`

搜索根策略：

1. 先用配置的 `baseDn`
2. 如果未命中，再回退到整个域根 `DC=xgd,DC=com`

设计原因：

- 当前服务账号 `ssc-skills` 的实际 DN 是 `CN=ssc-skills,OU=LDAPCN,DC=xgd,DC=com`
- 它并不在默认配置的 OU 下
- 如果不做域根回退，会出现“认证成功但 LDAP 查不到用户”的误判

生产版推荐补充：

- 搜索条件应以“待验证用户”的 `principal` 和 `accountName` 为准
- 不要用 LDAP 服务账号的账号名去搜索，否则会查错对象

返回规则：

- 取第一条结果
- 结果数量上限为 `2`
- 返回全部属性，不限制字段清单

## 6. 姓名解析规则

程序当前的姓名解析顺序如下：

1. `sn + givenName`
2. `displayName`
3. `cn`
4. `name`

当前账号 `ssc-skills` 的真实结果：

- `sn = 技能`
- `givenName = 测试`
- `displayName = ssc-skills`
- 最终 `ldap name = 技能测试`
- `name source = sn+givenName`

这说明：

- “显示名”不一定等于“真实姓名”
- AD 中用于真实姓名的字段优先应看 `sn` 和 `givenName`

## 7. 标准输出契约

当前成功输出顺序固定如下：

```text
kerberos login success
principal: <principal>
ticket count: <count>
ldap lookup success
ldap name: <解析后的姓名>
surname: <sn>
given name: <givenName>
display name: <displayName>
cn: <cn>
name: <name>
sAMAccountName: <sAMAccountName>
userPrincipalName: <userPrincipalName>
name source: <姓名来源>
distinguished name: <dn>
ldap attributes:
  <attribute1>: <value1>
  <attribute2>: <value2>
```

字段含义：

- `ldap name`：最终对外展示的姓名
- `name source`：姓名来源，值可能为 `sn+givenName`、`displayName`、`cn`、`name`
- `ldap attributes`：LDAP 返回的全部非空属性，按属性名排序输出

二进制属性输出规则：

- 当前会同时输出 `base64` 和 `hex`
- 例如 `objectGUID`、`objectSid`

空值输出规则：

- 结构化字段为空时输出 `<empty>`

## 8. 失败处理规则

### 8.1 参数错误

场景：

- 缺少密码
- 参数缺值
- 未知参数

行为：

- 打印错误信息和 usage
- 退出码 `2`

### 8.2 Kerberos 失败

当前分类逻辑：

- `clock skew` -> 本机时间与域控时间偏差过大
- `pre-authentication information was invalid` / `password incorrect` / `integrity check on decrypted field failed` -> 账号或密码错误
- `client not found in kerberos database` -> 账号不存在，或 principal 格式不正确
- `cannot contact any kdc` / `connection refused` / `no route to host` -> 无法连接 KDC
- `cannot locate kdc` / `cannot find kdc for realm` / `realm not local to kdc` -> Realm 或 KDC 配置错误
- `kdc has no support for encryption type` -> 加密类型不兼容
- 其他 -> Kerberos 认证失败

行为：

- 打印 `kerberos login failed`
- 打印 `reason`
- 打印最底层异常信息 `detail`
- 退出码 `1`

### 8.3 LDAP 失败

当前分类逻辑：

- `invalid credentials` -> LDAP 绑定失败，账号或密码错误
- `connect error` / `connection refused` / `socket closed` / `read timed out` -> 无法连接 LDAP 服务
- `no such object` -> Base DN 不存在
- `size limit exceeded` -> 搜索结果过多
- 其他 -> LDAP 查询失败

行为：

- 打印 `ldap lookup failed`
- 打印 `reason`
- 打印最底层异常信息 `detail`
- 退出码 `1`

## 9. 生产版必须保留的约束

这些约束在 Python 重构时建议继续保留：

- Kerberos 认证与 LDAP 查询是两个阶段，不要合并成单个黑盒调用
- Kerberos 成功不代表 LDAP 一定能查到用户
- LDAP 搜索根必须支持“指定 OU + 域根回退”
- 姓名显示不能只看 `displayName`
- LDAP bind 身份与待验证用户身份必须解耦
- 输出中要同时保留：
- 业务字段
- 原始 LDAP 属性
- principal 和 DN

生产版建议新增约束：

- LDAP 服务账号只授予最小只读权限
- 服务账号密码不能进入标准输出
- 服务账号配置优先从环境变量或受控配置读取，不建议写死
- 认证失败时不要自动改用服务账号去“代替用户认证”，两者职责不能混淆

## 10. Python 重构建议

建议按职责拆分，不要把所有逻辑堆到一个脚本里。

推荐模块划分：

- `config`
- 负责参数读取、环境变量合并、默认值管理
- `identity`
- 负责用户名、principal、realm、baseDn 归一化
- `kerberos_auth`
- 只负责 Kerberos 登录和返回 principal / ticket 信息
- `ldap_client`
- 只负责 LDAP 服务账号 bind、search、属性读取
- `user_mapper`
- 负责姓名解析和属性映射
- `cli`
- 负责标准输出和退出码

推荐数据对象：

- `ProgramOptions`
- `KerberosResult`
- `LdapUserInfo`
- `ResolvedName`
- `LdapBindConfig`

推荐保留的函数职责：

- `normalize_principal`
- `normalize_base_dn`
- `build_ldap_service_bind_principals`
- `build_ldap_bind_principals`
- `build_search_bases`
- `resolve_ldap_name`
- `collect_attributes`
- `classify_kerberos_failure`
- `classify_ldap_failure`

其中建议调整为：

- `build_ldap_bind_principals` 用于服务账号，不再用于待验证用户
- 如果保留旧逻辑，单独提供 `build_user_bind_principals_for_fallback`

## 11. Python 重构验收标准

Python 版本完成后，至少要满足以下验收项：

- 支持输入账号密码验证 Kerberos
- 能返回 principal
- 能通过 LDAP 服务账号查询到对应用户
- 能按当前规则解析 `ldap name`
- 能打印 `sn`、`givenName`、`displayName`、`cn`、`name`、`sAMAccountName`、`userPrincipalName`
- 能输出全部非空 LDAP 属性
- 支持 OU 简写路径自动转标准 DN
- 支持指定 OU 失败后回退到域根查询
- 对错误原因有明确分类
- 成功和失败时的退出码与当前版本一致
- LDAP 查询链路默认不依赖待验证用户自己的目录权限

生产版新增验收项：

- 没有配置 LDAP 服务账号时，程序应明确报配置错误，而不是静默回退
- 日志中不得输出 LDAP 服务账号密码
- 搜索目标必须是待验证用户，而不是服务账号自己

## 12. 当前实测基线

当前 Java 版本针对账号 `ssc-skills` 的实测结果如下：

- Kerberos 登录成功
- principal：`ssc-skills@XGD.COM`
- LDAP 查询成功
- `surname = 技能`
- `givenName = 测试`
- `ldap name = 技能测试`
- DN：`CN=ssc-skills,OU=LDAPCN,DC=xgd,DC=com`

这个结果可以作为 Python 重构后的对比基线。

补充说明：

- 当前 Java 版本还是“用户自己 Kerberos + 用户自己 LDAP bind”的测试实现
- Python 重构时应改成“用户 Kerberos + 服务账号 LDAP bind”的生产版推荐流程
