# Changelog

## [0.2.10](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.9...freeciv3d-v0.2.10) (2025-12-29)


### Bug Fixes

* **k8s:** Add /freeciv-web context path to observer URLs ([#34](https://github.com/taso-ventures/freeciv3d/issues/34)) ([7832b53](https://github.com/taso-ventures/freeciv3d/commit/7832b53331075f886a419ddaec4b02f9da16ff21))

## [0.2.9](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.8...freeciv3d-v0.2.9) (2025-12-28)


### Bug Fixes

* **llm-gateway:** Add polling to observer-urls to fix race condition ([#32](https://github.com/taso-ventures/freeciv3d/issues/32)) ([68dbd54](https://github.com/taso-ventures/freeciv3d/commit/68dbd540b175d454d6096f7fce5104f6cdac0f9f))

## [0.2.8](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.7...freeciv3d-v0.2.8) (2025-12-28)


### Bug Fixes

* **k8s:** Configure public HTTPS URLs for observer iframes ([#30](https://github.com/taso-ventures/freeciv3d/issues/30)) ([1beaa2b](https://github.com/taso-ventures/freeciv3d/commit/1beaa2b377168364df42f7070b13ddbd2ce9c221))

## [0.2.7](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.6...freeciv3d-v0.2.7) (2025-12-27)


### Bug Fixes

* **flyway:** Run repair before migrate to handle failed migrations ([#28](https://github.com/taso-ventures/freeciv3d/issues/28)) ([1ea723e](https://github.com/taso-ventures/freeciv3d/commit/1ea723ea1ac4b918cd3309e42fbc6f2e0f9617a0))

## [0.2.6](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.5...freeciv3d-v0.2.6) (2025-12-27)


### Features

* **k8s:** Add Flyway database migrations to CI/CD ([#26](https://github.com/taso-ventures/freeciv3d/issues/26)) ([ca05c71](https://github.com/taso-ventures/freeciv3d/commit/ca05c71082eba7856997de6b1ec86b556124c1bb))

## [0.2.5](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.4...freeciv3d-v0.2.5) (2025-12-26)


### Bug Fixes

* **ci:** Sync VERSION file and fix deploy workflows to use release tags ([#24](https://github.com/taso-ventures/freeciv3d/issues/24)) ([081f301](https://github.com/taso-ventures/freeciv3d/commit/081f301f27dca538b213766103aaf6e42eba69d6))

## [0.2.4](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.3...freeciv3d-v0.2.4) (2025-12-26)


### Bug Fixes

* **k8s:** Fix Cloud SQL connectivity and add public Ingress for observer mode ([#22](https://github.com/taso-ventures/freeciv3d/issues/22)) ([e173deb](https://github.com/taso-ventures/freeciv3d/commit/e173debec1eb3e180c67e874d303460b0f5fe992))

## [0.2.3](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.2...freeciv3d-v0.2.3) (2025-12-25)


### Bug Fixes

* **ci:** Remove branches filter from deploy-staging workflow_run ([8ae5db5](https://github.com/taso-ventures/freeciv3d/commit/8ae5db5390f22ec7f573b47ee1131ba58cbe1710))
* **k8s:** Fix fciv-net deployment probes, ports, and security context ([#21](https://github.com/taso-ventures/freeciv3d/issues/21)) ([6fcb60d](https://github.com/taso-ventures/freeciv3d/commit/6fcb60defb7578b84a02d5d214648cecfd96d86c))

## [0.2.2](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.1...freeciv3d-v0.2.2) (2025-12-25)


### Bug Fixes

* **ci:** Pull staging image before tagging for production ([77ac120](https://github.com/taso-ventures/freeciv3d/commit/77ac120ebd6b14696f6734a08296ed9c84780c68))


### Code Refactoring

* **ci:** Align with agent-clash pattern - gcrane for image promotion ([5ca52b8](https://github.com/taso-ventures/freeciv3d/commit/5ca52b88711c17c6d8c4bcbdc18794593a6a0724))

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
