## MODIFIED Requirements

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
