## Purpose

定义 AD 用户登录后组织架构的归一化解析、持久化刷新，以及面向用户中心的组织层级数据暴露规则。

## Requirements

### Requirement: AD users SHALL persist a normalized organization hierarchy from OU path
The system SHALL parse the AD user's `distinguishedName` on successful AD authentication, remove the shared top-level root OU, and persist at most 4 organization levels in high-to-low order.

#### Scenario: Four-level hierarchy is derived from OU path
- **WHEN** an AD user logs in with `CN=谢金城,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com`
- **THEN** the system MUST persist `支付硬件事业群` as level 1, `技术中心` as level 2, `公共技术中心` as level 3, and `系统方案部` as level 4

#### Scenario: Shared root OU is excluded from persisted hierarchy
- **WHEN** an AD user's DN contains a top-level shared root OU above the business organization path
- **THEN** the system MUST exclude that root OU from the persisted organization hierarchy

#### Scenario: Missing lower levels remain empty
- **WHEN** an AD user's effective business organization path contains fewer than 4 levels after root removal
- **THEN** the system MUST persist only the available levels and MUST leave the remaining lower-level fields empty

### Requirement: AD organization hierarchy SHALL refresh on every successful AD login
The system SHALL recompute and overwrite the cached AD organization hierarchy every time an AD user successfully logs in.

#### Scenario: Organization change is reflected on next login
- **WHEN** an AD user's OU path changes in the domain and the user logs in again
- **THEN** the system MUST overwrite the previously cached organization levels with the newly derived hierarchy

#### Scenario: Existing AD user keeps latest DN snapshot
- **WHEN** an existing AD user logs in successfully
- **THEN** the system MUST update both the stored distinguished name snapshot and the normalized organization hierarchy in the same sync flow

### Requirement: User-facing APIs SHALL expose the normalized organization hierarchy
The system SHALL expose the AD user's normalized organization hierarchy to authenticated user-facing APIs that power the user center.

#### Scenario: User center reads a four-level hierarchy
- **WHEN** the frontend requests the current authenticated user's profile after an AD user logs in
- **THEN** the response MUST include the normalized organization hierarchy fields in level order for display

#### Scenario: User center reads a partial hierarchy
- **WHEN** the authenticated AD user only has 2 or 3 effective organization levels
- **THEN** the response MUST include the available levels and MUST represent the missing lower levels as empty values
