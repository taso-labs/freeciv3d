# Changelog

## [0.3.15](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.14...freeciv3d-v0.3.15) (2026-01-20)


### CI/CD

* Add Flyway migration testing against MySQL 8.0 ([#70](https://github.com/taso-ventures/freeciv3d/issues/70)) ([93dcdd6](https://github.com/taso-ventures/freeciv3d/commit/93dcdd6d3302614536511fa03257f11b301152bc))

## [0.3.14](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.13...freeciv3d-v0.3.14) (2026-01-20)


### Bug Fixes

* **db:** Remove invalid IF NOT EXISTS syntax from CREATE INDEX ([293261a](https://github.com/taso-ventures/freeciv3d/commit/293261a2cc05c7fb9a3f26781cfa1031e9f19da2))

## [0.3.13](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.12...freeciv3d-v0.3.13) (2026-01-20)


### Bug Fixes

* **db:** Remove MySQL Event Scheduler dependency from migrations ([#66](https://github.com/taso-ventures/freeciv3d/issues/66)) ([1b33b0a](https://github.com/taso-ventures/freeciv3d/commit/1b33b0aae62d4bcb11744d4e1adf3d60b68b2911))
* **tests:** Fix failing Python tests and add CI integration ([#67](https://github.com/taso-ventures/freeciv3d/issues/67)) ([18c0e84](https://github.com/taso-ventures/freeciv3d/commit/18c0e84b7081cca03edb270e93818bc624e4a2b6))

## [0.3.12](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.11...freeciv3d-v0.3.12) (2026-01-19)


### Bug Fixes

* **proxy:** Add moves_left checks to prevent E024 errors in legal actions ([#64](https://github.com/taso-ventures/freeciv3d/issues/64)) ([86a201e](https://github.com/taso-ventures/freeciv3d/commit/86a201e715e928e483021b90db694e1f1e2522f7))

## [0.3.11](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.10...freeciv3d-v0.3.11) (2026-01-17)


### Bug Fixes

* Stability improvements for LLM agent matches and WebGL rendering ([#62](https://github.com/taso-ventures/freeciv3d/issues/62)) ([a16a528](https://github.com/taso-ventures/freeciv3d/commit/a16a528b189b0d95d8d74bc62229c796b5236d3d))

## [0.3.10](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.9...freeciv3d-v0.3.10) (2026-01-14)


### Bug Fixes

* **observability:** Fix tracing export failures and match startup issues ([#60](https://github.com/taso-ventures/freeciv3d/issues/60)) ([fb06119](https://github.com/taso-ventures/freeciv3d/commit/fb06119c25bbe7be0419088b27febc26b741e2da))

## [0.3.9](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.8...freeciv3d-v0.3.9) (2026-01-14)


### Bug Fixes

* **k8s:** Convert GATEWAY_FREECIV_WEB_BASE_URL to strategic merge patch ([540f961](https://github.com/taso-ventures/freeciv3d/commit/540f96139f972c4aa7aeab5a7a90bf0434296448))

## [0.3.8](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.7...freeciv3d-v0.3.8) (2026-01-14)


### Features

* **observability:** Add distributed tracing with OpenTelemetry and GCP Cloud Trace ([#57](https://github.com/taso-ventures/freeciv3d/issues/57)) ([320268c](https://github.com/taso-ventures/freeciv3d/commit/320268c05aa9771ae930f9ac67d3274b936deffc))

## [0.3.7](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.6...freeciv3d-v0.3.7) (2026-01-13)


### Bug Fixes

* **reconnection:** Skip PACKET_CONN_INFO wait when resuming session ([#55](https://github.com/taso-ventures/freeciv3d/issues/55)) ([f351c08](https://github.com/taso-ventures/freeciv3d/commit/f351c08210ed3d2a8ae133552e16fe4578fefa0f))

## [0.3.6](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.5...freeciv3d-v0.3.6) (2026-01-13)


### Features

* **streaming:** Add YouTube Live streaming for FreeCiv AI matches ([#53](https://github.com/taso-ventures/freeciv3d/issues/53)) ([bef2d0c](https://github.com/taso-ventures/freeciv3d/commit/bef2d0c525b301597c43d67ad8bd24660ee8ecee))

## [0.3.5](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.4...freeciv3d-v0.3.5) (2026-01-07)


### Features

* **ci:** Add Slack CI/CD notifications to deployment workflows ([#49](https://github.com/taso-ventures/freeciv3d/issues/49)) ([f676661](https://github.com/taso-ventures/freeciv3d/commit/f67666187a25a4ee3f1a75cd91883f32b328f912))


### Bug Fixes

* **proxy:** Address code review blockers for pause/resume functionality ([#51](https://github.com/taso-ventures/freeciv3d/issues/51)) ([d5c9082](https://github.com/taso-ventures/freeciv3d/commit/d5c9082d5fbd60359b449b6e34c9ef5b77387450))


### Documentation

* Add CLAUDE.md development guidelines to repository ([#52](https://github.com/taso-ventures/freeciv3d/issues/52)) ([33cf2b3](https://github.com/taso-ventures/freeciv3d/commit/33cf2b3b4066f238002e04c223f370741cfad381))

## [0.3.4](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.3...freeciv3d-v0.3.4) (2026-01-01)


### Bug Fixes

* **k8s:** Add apex domain to CSP frame-ancestors for iframe embedding ([5a1a4af](https://github.com/taso-ventures/freeciv3d/commit/5a1a4afd029dc16833b8fe8c6897a32e5a84abab))

## [0.3.3](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.2...freeciv3d-v0.3.3) (2026-01-01)


### Bug Fixes

* Password escaping + staging deployment strategy ([#46](https://github.com/taso-ventures/freeciv3d/issues/46)) ([08a76c4](https://github.com/taso-ventures/freeciv3d/commit/08a76c4210366d1e4c2e44b20f5207705f21076e))

## [0.3.2](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.1...freeciv3d-v0.3.2) (2025-12-30)


### Bug Fixes

* **k8s:** Reduce production resource requests to fit e2-small nodes ([f39ea96](https://github.com/taso-ventures/freeciv3d/commit/f39ea968512575343551d8589a18d7c4225e9d57))
* **proxy:** Enable agent session reconnection after WebSocket disconnect ([#45](https://github.com/taso-ventures/freeciv3d/issues/45)) ([f92de13](https://github.com/taso-ventures/freeciv3d/commit/f92de136e639cd35b6fb5dc4967584f332763f5c))

## [0.3.1](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.0...freeciv3d-v0.3.1) (2025-12-29)


### Bug Fixes

* **k8s:** Add port 8081 to NetworkPolicy for nginx sidecar health checks ([d119353](https://github.com/taso-ventures/freeciv3d/commit/d119353c49745fa410581e13df405e4fa9c1fa61))
* **ngix:** allow observer mode port forwarding ([669d1e7](https://github.com/taso-ventures/freeciv3d/commit/669d1e75aa04950a0d434270f79edf652300a9ab))

## [0.3.0](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.13...freeciv3d-v0.3.0) (2025-12-29)


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
* **k8s:** Add Flyway database migrations to CI/CD ([#26](https://github.com/taso-ventures/freeciv3d/issues/26)) ([ca05c71](https://github.com/taso-ventures/freeciv3d/commit/ca05c71082eba7856997de6b1ec86b556124c1bb))
* **k8s:** Add nginx sidecar for observer WebSocket support ([b97a65f](https://github.com/taso-ventures/freeciv3d/commit/b97a65f6eb13f1d773fc13b97462fccda754d546))
* **k8s:** Consolidate to monolithic architecture - llm-gateway in fciv-net ([#17](https://github.com/taso-ventures/freeciv3d/issues/17)) ([351e07c](https://github.com/taso-ventures/freeciv3d/commit/351e07c21b66b2ba30d2d4171854a49fef150cb9))
* **observer:** Add observer streaming for iframe embedding ([#15](https://github.com/taso-ventures/freeciv3d/issues/15)) ([d839437](https://github.com/taso-ventures/freeciv3d/commit/d839437690723128677617fc80c423b71788eb77))


### Bug Fixes

* **ci:** Correct Workload Identity Pool/Provider names ([df83090](https://github.com/taso-ventures/freeciv3d/commit/df830905737a12c37a94bc988e68f203dc3cc3e5))
* **ci:** Pull staging image before tagging for production ([77ac120](https://github.com/taso-ventures/freeciv3d/commit/77ac120ebd6b14696f6734a08296ed9c84780c68))
* **ci:** Remove branches filter from deploy-staging workflow_run ([8ae5db5](https://github.com/taso-ventures/freeciv3d/commit/8ae5db5390f22ec7f573b47ee1131ba58cbe1710))
* **ci:** Sync VERSION file and fix deploy workflows to use release tags ([#24](https://github.com/taso-ventures/freeciv3d/issues/24)) ([081f301](https://github.com/taso-ventures/freeciv3d/commit/081f301f27dca538b213766103aaf6e42eba69d6))
* **docker:** Update startup scripts for ROOT.war context path ([#38](https://github.com/taso-ventures/freeciv3d/issues/38)) ([837e0e2](https://github.com/taso-ventures/freeciv3d/commit/837e0e256c8efe60771f02e06ed3899040c9cb17))
* **flyway:** Run repair before migrate to handle failed migrations ([#28](https://github.com/taso-ventures/freeciv3d/issues/28)) ([1ea723e](https://github.com/taso-ventures/freeciv3d/commit/1ea723ea1ac4b918cd3309e42fbc6f2e0f9617a0))
* **k8s:** Add /freeciv-web context path to observer URLs ([#34](https://github.com/taso-ventures/freeciv3d/issues/34)) ([7832b53](https://github.com/taso-ventures/freeciv3d/commit/7832b53331075f886a419ddaec4b02f9da16ff21))
* **k8s:** Add explicit health check path to BackendConfig for ROOT.war ([790269a](https://github.com/taso-ventures/freeciv3d/commit/790269a980b4d6ddb53950aa143f8799f51c06e2))
* **k8s:** Configure public HTTPS URLs for observer iframes ([#30](https://github.com/taso-ventures/freeciv3d/issues/30)) ([1beaa2b](https://github.com/taso-ventures/freeciv3d/commit/1beaa2b377168364df42f7070b13ddbd2ce9c221))
* **k8s:** Deploy WAR as ROOT.war to fix static resource 404s ([#36](https://github.com/taso-ventures/freeciv3d/issues/36)) ([7eda6b0](https://github.com/taso-ventures/freeciv3d/commit/7eda6b0d297d63878d7ba6d2badc97d7a0b5f7b9))
* **k8s:** Fix Cloud SQL connectivity and add public Ingress for observer mode ([#22](https://github.com/taso-ventures/freeciv3d/issues/22)) ([e173deb](https://github.com/taso-ventures/freeciv3d/commit/e173debec1eb3e180c67e874d303460b0f5fe992))
* **k8s:** Fix fciv-net deployment probes, ports, and security context ([#21](https://github.com/taso-ventures/freeciv3d/issues/21)) ([6fcb60d](https://github.com/taso-ventures/freeciv3d/commit/6fcb60defb7578b84a02d5d214648cecfd96d86c))
* **k8s:** Use nginx-unprivileged image on port 8081 ([61e5746](https://github.com/taso-ventures/freeciv3d/commit/61e5746dc477bd2bce98fe64b6e9d976a4d3ad9b))
* **llm-gateway:** Add polling to observer-urls to fix race condition ([#32](https://github.com/taso-ventures/freeciv3d/issues/32)) ([68dbd54](https://github.com/taso-ventures/freeciv3d/commit/68dbd540b175d454d6096f7fce5104f6cdac0f9f))
* **llm-gateway:** Return legal_actions as dict keyed by actor_id for O(1) lookup ([#14](https://github.com/taso-ventures/freeciv3d/issues/14)) ([7266633](https://github.com/taso-ventures/freeciv3d/commit/72666338f8e3ed4d39a41bf17a3afb33d042f80a))
* **nginx:** Use localhost instead of fciv-net for K8s compatibility ([e3f9d7a](https://github.com/taso-ventures/freeciv3d/commit/e3f9d7a493ea5f66f88a70beb43bb2168dd96afb))
* startup scripts now working ([#1](https://github.com/taso-ventures/freeciv3d/issues/1)) ([6e6f700](https://github.com/taso-ventures/freeciv3d/commit/6e6f700e211baa28324f448bdaa1a103cb04bdd9))


### Code Refactoring

* **ci:** Align with agent-clash pattern - gcrane for image promotion ([5ca52b8](https://github.com/taso-ventures/freeciv3d/commit/5ca52b88711c17c6d8c4bcbdc18794593a6a0724))
* remove spectator mode in favor of existing observer functionality ([#7](https://github.com/taso-ventures/freeciv3d/issues/7)) ([e052b56](https://github.com/taso-ventures/freeciv3d/commit/e052b5616805bf5a1c0fd284ace98643bac2d4c0))


### Miscellaneous

* **main:** release freeciv3d 0.2.0 ([#16](https://github.com/taso-ventures/freeciv3d/issues/16)) ([b02fe59](https://github.com/taso-ventures/freeciv3d/commit/b02fe5983d0e6c1c18b5d3d3aefe1b5c60d6d53c))
* **main:** release freeciv3d 0.2.1 ([#18](https://github.com/taso-ventures/freeciv3d/issues/18)) ([e86d7c4](https://github.com/taso-ventures/freeciv3d/commit/e86d7c4ec4b3c41fcb120b28efd5a8a89ab70869))
* **main:** release freeciv3d 0.2.10 ([#35](https://github.com/taso-ventures/freeciv3d/issues/35)) ([346ecf2](https://github.com/taso-ventures/freeciv3d/commit/346ecf25b0e61f80fcecb45ec6c73ad46b840607))
* **main:** release freeciv3d 0.2.11 ([#37](https://github.com/taso-ventures/freeciv3d/issues/37)) ([2bebbd4](https://github.com/taso-ventures/freeciv3d/commit/2bebbd4ec06fc22bd90bc68a1fa377e3a880b7ac))
* **main:** release freeciv3d 0.2.12 ([#39](https://github.com/taso-ventures/freeciv3d/issues/39)) ([94fce1d](https://github.com/taso-ventures/freeciv3d/commit/94fce1d48f691ce216334c96d0facc65e5b0cb2f))
* **main:** release freeciv3d 0.2.13 ([#41](https://github.com/taso-ventures/freeciv3d/issues/41)) ([182759b](https://github.com/taso-ventures/freeciv3d/commit/182759b68852a65bcbf4519d07ba0bbbfedc967a))
* **main:** release freeciv3d 0.2.2 ([#19](https://github.com/taso-ventures/freeciv3d/issues/19)) ([1296ef9](https://github.com/taso-ventures/freeciv3d/commit/1296ef96350b70980db259fc535f53de3294359b))
* **main:** release freeciv3d 0.2.3 ([#20](https://github.com/taso-ventures/freeciv3d/issues/20)) ([cf5c317](https://github.com/taso-ventures/freeciv3d/commit/cf5c317084f8381d02640ac9b0b32e129125112f))
* **main:** release freeciv3d 0.2.4 ([#23](https://github.com/taso-ventures/freeciv3d/issues/23)) ([d7f12a5](https://github.com/taso-ventures/freeciv3d/commit/d7f12a5f4d8fd0905a4185db4f44cf92731476c4))
* **main:** release freeciv3d 0.2.5 ([#25](https://github.com/taso-ventures/freeciv3d/issues/25)) ([22f88a9](https://github.com/taso-ventures/freeciv3d/commit/22f88a990b4c64fdffa35f721e39f1fe50b5a2ce))
* **main:** release freeciv3d 0.2.6 ([#27](https://github.com/taso-ventures/freeciv3d/issues/27)) ([f563480](https://github.com/taso-ventures/freeciv3d/commit/f5634800044711f45ff91893128c302aab74c5d3))
* **main:** release freeciv3d 0.2.7 ([#29](https://github.com/taso-ventures/freeciv3d/issues/29)) ([4ec6c31](https://github.com/taso-ventures/freeciv3d/commit/4ec6c31ded06f7f9aa305fe6f1bd3276f8f55bf3))
* **main:** release freeciv3d 0.2.8 ([#31](https://github.com/taso-ventures/freeciv3d/issues/31)) ([5bd2c8b](https://github.com/taso-ventures/freeciv3d/commit/5bd2c8bdd6ccce1811d04551a3c6b6e4a12b6771))
* **main:** release freeciv3d 0.2.9 ([#33](https://github.com/taso-ventures/freeciv3d/issues/33)) ([699e6d1](https://github.com/taso-ventures/freeciv3d/commit/699e6d13598ee6c07e5de76cbff2c9ea4be94730))
* trigger release-please for v0.2.14 ([3c98c92](https://github.com/taso-ventures/freeciv3d/commit/3c98c923b6b2f221a8487a4a72414379ca1e7da9))

## [0.2.13](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.12...freeciv3d-v0.2.13) (2025-12-29)


### Features

* **k8s:** Add nginx sidecar for observer WebSocket support ([b97a65f](https://github.com/taso-ventures/freeciv3d/commit/b97a65f6eb13f1d773fc13b97462fccda754d546))


### Bug Fixes

* **k8s:** Add explicit health check path to BackendConfig for ROOT.war ([790269a](https://github.com/taso-ventures/freeciv3d/commit/790269a980b4d6ddb53950aa143f8799f51c06e2))
* **k8s:** Use nginx-unprivileged image on port 8081 ([61e5746](https://github.com/taso-ventures/freeciv3d/commit/61e5746dc477bd2bce98fe64b6e9d976a4d3ad9b))
* **nginx:** Use localhost instead of fciv-net for K8s compatibility ([e3f9d7a](https://github.com/taso-ventures/freeciv3d/commit/e3f9d7a493ea5f66f88a70beb43bb2168dd96afb))

## [0.2.12](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.11...freeciv3d-v0.2.12) (2025-12-29)


### Bug Fixes

* **docker:** Update startup scripts for ROOT.war context path ([#38](https://github.com/taso-ventures/freeciv3d/issues/38)) ([837e0e2](https://github.com/taso-ventures/freeciv3d/commit/837e0e256c8efe60771f02e06ed3899040c9cb17))

## [0.2.11](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.2.10...freeciv3d-v0.2.11) (2025-12-29)


### Bug Fixes

* **k8s:** Deploy WAR as ROOT.war to fix static resource 404s ([#36](https://github.com/taso-ventures/freeciv3d/issues/36)) ([7eda6b0](https://github.com/taso-ventures/freeciv3d/commit/7eda6b0d297d63878d7ba6d2badc97d7a0b5f7b9))

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
