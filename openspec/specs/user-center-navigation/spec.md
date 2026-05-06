## Purpose

定义登录后顶部导航的收敛规则、教程入口的内容组织方式，以及用户中心内部的私有管理模块切换行为。

## Requirements

### Requirement: Authenticated header navigation is consolidated into user center entry
The system SHALL simplify the authenticated top navigation to home, guide, user center entry, and logout, and SHALL use the current user's displayed name as the entry to user center.

#### Scenario: Logged-in user sees simplified top navigation
- **WHEN** a signed-in user views the header
- **THEN** the system MUST show home, guide, user center entry, and logout without separately listing workspace, group management, or user management as top-level menu items

#### Scenario: Clicking user name enters user center
- **WHEN** a signed-in user clicks their displayed name in the header
- **THEN** the system MUST navigate to user center

### Requirement: Guide entry includes CLI installation and usage instructions
The system SHALL merge CLI installation guidance into the guide entry and SHALL stop exposing a separate top-level CLI installation menu.

#### Scenario: Guide shows installation and usage content together
- **WHEN** a user opens the guide entry
- **THEN** the system MUST present CLI installation instructions together with subsequent usage steps in the same tutorial experience

#### Scenario: No separate CLI menu remains
- **WHEN** a user views the top navigation
- **THEN** the system MUST NOT show a standalone CLI installation menu item

### Requirement: User center provides permission-aware switching between private modules
The system SHALL present private management pages inside user center, SHALL expose only the module switches that the current user is authorized to access, and SHALL display the current authenticated user's normalized organization hierarchy inside the user center profile area. Administrators MUST see Skill management, group management, and user management. Non-administrators MUST see group management whenever they are a leader of at least one group or a member of at least one group, and that access SHALL remain read-only for users who are members but not managers of the selected group.

#### Scenario: Administrator sees all management switches
- **WHEN** an administrator enters user center
- **THEN** the system MUST provide switching controls for Skill management, group management, and user management

#### Scenario: Group member sees group management switch
- **WHEN** a non-administrator user belongs to at least one group
- **THEN** the system MUST show the group management switch in user center

#### Scenario: User without group access does not see group management switch
- **WHEN** a non-administrator user does not lead any group and does not belong to any group
- **THEN** the system MUST hide the group management switch

#### Scenario: AD user sees normalized organization hierarchy in user center
- **WHEN** an AD user enters user center after a successful login
- **THEN** the system MUST display the user's available organization hierarchy levels in order and MUST omit or visually mark missing lower levels when the hierarchy has fewer than 4 levels
