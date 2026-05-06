## Purpose

定义 Skill 与可见范围的绑定规则，以及首页和本地详情接口基于公开、用户组、组织架构三类范围的可见性控制。

## Requirements

### Requirement: Skill owners can bind a skill to one eligible visibility scope
The system SHALL allow a local Skill to reference zero or one visibility scope, and SHALL allow that scope to be set during Skill creation or update as either public, group, or organization scope.

#### Scenario: Administrator can bind a Skill to any group
- **WHEN** an administrator creates or updates a local Skill and selects group scope with an existing group
- **THEN** the system MUST save that group as the Skill's visibility scope

#### Scenario: Ordinary user can only bind to own groups
- **WHEN** a non-administrator creates or updates a local Skill and selects group scope
- **THEN** the system MUST only allow selecting groups that already include that user as a member

#### Scenario: Binding to an unrelated group is rejected
- **WHEN** a non-administrator submits a group ID for a group they do not belong to
- **THEN** the system MUST reject the request

#### Scenario: Public scope keeps the skill visible without group binding
- **WHEN** a user creates or updates a local Skill and selects public scope
- **THEN** the system MUST save the Skill without any group or organization binding

### Requirement: Scoped skills are filtered from the local homepage by the selected visibility rule
The system SHALL include a public local Skill in the local homepage for all visitors, SHALL include a group-scoped local Skill only for administrators or members of the bound group, and SHALL include an organization-scoped local Skill only for administrators or users whose organization hierarchy matches the scoped organization path or its descendants.

#### Scenario: Anonymous visitor sees only public local skills
- **WHEN** an anonymous visitor requests the local homepage skill list
- **THEN** the system MUST exclude every local Skill that is bound to a group or organization scope

#### Scenario: Group member sees the group's scoped skills
- **WHEN** a logged-in user requests the local homepage skill list and belongs to a Skill's bound group
- **THEN** the system MUST include that Skill in the local results

#### Scenario: Organization descendant sees the organization's scoped skills
- **WHEN** a logged-in user requests the local homepage skill list and the user's organization hierarchy is within the Skill's scoped organization path
- **THEN** the system MUST include that Skill in the local results

#### Scenario: Non-member and unrelated organization do not see scoped skills
- **WHEN** a logged-in non-administrator requests the local homepage skill list and neither belongs to the Skill's bound group nor falls under the Skill's scoped organization path
- **THEN** the system MUST exclude that Skill from the local results

### Requirement: Scoped skill detail endpoints enforce the same visibility rule
The system SHALL apply the same selected visibility rule to local Skill detail and version detail endpoints, and unauthorized requests MUST receive a not-found response.

#### Scenario: Group member opens scoped skill detail successfully
- **WHEN** a logged-in user requests a local Skill detail or local Skill version detail for a Skill whose bound group includes that user
- **THEN** the system MUST return the Skill detail

#### Scenario: Organization descendant opens scoped skill detail successfully
- **WHEN** a logged-in user requests a local Skill detail or local Skill version detail for a Skill whose scoped organization path is an ancestor of the user's organization path
- **THEN** the system MUST return the Skill detail

#### Scenario: Unauthorized detail request is hidden as not found
- **WHEN** an anonymous visitor or unrelated logged-in user requests a local Skill detail or local Skill version detail for a non-public Skill
- **THEN** the system MUST respond as if the Skill does not exist

### Requirement: Scope visibility does not grant workspace management permissions
The system SHALL keep workspace management authority based on Skill ownership and administrator role, rather than group membership or organization visibility.

#### Scenario: Visible user cannot manage another user's workspace skill
- **WHEN** a user can view a Skill because of the same group or organization scope but is not that Skill's owner and is not an administrator
- **THEN** the system MUST continue rejecting workspace detail, update, and delete operations for that Skill

### Requirement: Groups referenced by group-scoped skills cannot be deleted
The system SHALL reject group deletion while any Skill remains bound to that group under group scope, so that deleting a group cannot implicitly broaden a Skill's visibility scope.

#### Scenario: Delete is blocked when a group-scoped Skill still references the group
- **WHEN** an administrator deletes a group that is still bound by at least one Skill using group scope
- **THEN** the system MUST reject the deletion and require the Skill binding to be removed or changed first

#### Scenario: Delete succeeds after all group-scope bindings are removed
- **WHEN** an administrator deletes a group after every group-scoped Skill has been unbound from that group or moved to another scope
- **THEN** the system MUST allow the deletion
