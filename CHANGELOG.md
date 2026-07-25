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
