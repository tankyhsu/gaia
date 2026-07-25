# Changelog

All notable user-visible Gaia changes are recorded here.

## Unreleased

### Added

- Added a Codex-native change-set workflow that keeps implementation, tests, documentation,
  generated contracts, and release impact synchronized.
- Added clean-environment GitHub quality and service-integration workflows for private development.
- External-model, scheduled, and release workflows remain disabled during the development phase.
- Consolidated local PostgreSQL and Redis into one optional development-infrastructure Compose;
  Gaia applications, Dev Console, and documentation now use native development commands.
- Registered the HR reference Showcase under the three business-facing Quick Start templates and
  added configurable Dev Console API and Showcase targets for local application development.
- Added auditable Codex hook forwarding for parent workspaces plus tracked Git commit and push gates,
  so missing workspace discovery can no longer silently bypass local Change Set verification.
