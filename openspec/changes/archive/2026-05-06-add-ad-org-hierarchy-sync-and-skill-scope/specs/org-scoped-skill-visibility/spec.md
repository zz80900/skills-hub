## ADDED Requirements

### Requirement: Skill owners SHALL be able to bind a skill to an organization scope
The system SHALL allow a local Skill to use organization scope as its visibility type, and SHALL persist the selected organization path together with its target level.

#### Scenario: Administrator binds a skill to any known organization node
- **WHEN** an administrator creates or updates a local Skill and selects organization scope with an existing organization node
- **THEN** the system MUST save the selected organization path and target level as the Skill's visibility scope

#### Scenario: Ordinary user binds a skill to current leaf organization
- **WHEN** a non-administrator creates or updates a local Skill and selects organization scope
- **THEN** the system MUST only allow binding the Skill to the user's current leaf organization node

#### Scenario: Binding to unrelated organization is rejected
- **WHEN** a non-administrator submits an organization path that is not the leaf node of the user's current hierarchy
- **THEN** the system MUST reject the request

### Requirement: Organization-scoped skills SHALL be visible to the bound organization and all descendants
The system SHALL allow a logged-in user to view an organization-scoped Skill when the user's normalized organization path matches the Skill's scope path exactly or extends it with deeper descendant levels.

#### Scenario: User in the exact scoped organization can view the skill
- **WHEN** a logged-in user belongs exactly to the organization path bound to the Skill
- **THEN** the system MUST include that Skill in visible results

#### Scenario: User in a child organization can view the ancestor-scoped skill
- **WHEN** a Skill is scoped to a 3-level organization path and a logged-in user belongs to a 4-level child path under the same first 3 levels
- **THEN** the system MUST include that Skill in visible results

#### Scenario: User from sibling organization cannot view the skill
- **WHEN** a Skill is scoped to one organization path and a logged-in user belongs to a different path that does not share the full scoped prefix
- **THEN** the system MUST exclude that Skill from visible results

### Requirement: Organization-scoped skill detail endpoints SHALL enforce the same hierarchy rule
The system SHALL apply the same organization visibility rule to local Skill detail and local Skill version detail endpoints, and unauthorized requests MUST receive a not-found response.

#### Scenario: Descendant department opens scoped skill detail successfully
- **WHEN** a logged-in user belongs to a descendant organization under the Skill's scoped path and requests local Skill detail
- **THEN** the system MUST return the Skill detail

#### Scenario: Unrelated department is hidden as not found
- **WHEN** an anonymous visitor, a local-only user without organization hierarchy, or a logged-in user from an unrelated organization requests local Skill detail for an organization-scoped Skill
- **THEN** the system MUST respond as if the Skill does not exist
