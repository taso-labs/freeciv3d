# Changelog

## [0.2.1](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.0...freeciv3d-v0.2.1) (2025-12-25)


### Bug Fixes

* **ci:** Correct Workload Identity Pool/Provider names ([df83090](https://github.com/taso-ventures/freeciv3d/commit/df830905737a12c37a94bc988e68f203dc3cc3e5))

## [0.2.0](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.1.0...freeciv3d-v0.2.0) (2025-12-25)


### ⚠ BREAKING CHANGES

* **llm-gateway:** `legal_actions` in state_update messages now returns a dict keyed by actor_id instead of a flat list. Client code must be updated to handle the new format.
* **AGE-192:** Collections now returned as dicts keyed by ID

### [feat

* **AGE-192:** Complete LLM Gateway protocol overhaul with critical fixes ([#8](https://github.com/taso-ventures/freeciv3d/issues/8)) ([b9adc39](https://github.com/taso-ventures/freeciv3d/commit/b9adc39688b5e257b59bff362f52e34a986a968d))


### Features

* **AGE-167, AGE-175:** Implement FC-3 WebSocket Protocol and FC-4 LLM Gateway with critical fixes ([#5](https://github.com/taso-ventures/freeciv3d/issues/5)) ([258f840](https://github.com/taso-ventures/freeciv3d/commit/258f8402730b598b78a08c2b8f1549875295972c))
* **deploy:** Add Kubernetes manifests for GKE deployment ([#10](https://github.com/taso-ventures/freeciv3d/issues/10)) ([94aaf28](https://github.com/taso-ventures/freeciv3d/commit/94aaf2879c12e10ebed32690460e1997cc9f501b))
* Enhanced freeciv-proxy with comprehensive LLM security features  ([#3](https://github.com/taso-ventures/freeciv3d/issues/3)) ([7d75fe3](https://github.com/taso-ventures/freeciv3d/commit/7d75fe3ad6e7ad1eab6df4b09b939d805cde8b4c))
* Implement FC-2 State Extraction Service for LLM integration ([#4](https://github.com/taso-ventures/freeciv3d/issues/4)) ([1ac193b](https://github.com/taso-ventures/freeciv3d/commit/1ac193b0ec33cf2c2ab2ca074fb0bad7407a1052))
* **k8s:** Consolidate to monolithic architecture - llm-gateway in fciv-net ([#17](https://github.com/taso-ventures/freeciv3d/issues/17)) ([351e07c](https://github.com/taso-ventures/freeciv3d/commit/351e07c21b66b2ba30d2d4171854a49fef150cb9))
* **observer:** Add observer streaming for iframe embedding ([#15](https://github.com/taso-ventures/freeciv3d/issues/15)) ([d839437](https://github.com/taso-ventures/freeciv3d/commit/d839437690723128677617fc80c423b71788eb77))


### Bug Fixes

* **llm-gateway:** Return legal_actions as dict keyed by actor_id for O(1) lookup ([#14](https://github.com/taso-ventures/freeciv3d/issues/14)) ([7266633](https://github.com/taso-ventures/freeciv3d/commit/72666338f8e3ed4d39a41bf17a3afb33d042f80a))
* startup scripts now working ([#1](https://github.com/taso-ventures/freeciv3d/issues/1)) ([6e6f700](https://github.com/taso-ventures/freeciv3d/commit/6e6f700e211baa28324f448bdaa1a103cb04bdd9))


### Code Refactoring

* remove spectator mode in favor of existing observer functionality ([#7](https://github.com/taso-ventures/freeciv3d/issues/7)) ([e052b56](https://github.com/taso-ventures/freeciv3d/commit/e052b5616805bf5a1c0fd284ace98643bac2d4c0))
