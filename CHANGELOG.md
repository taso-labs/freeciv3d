# Changelog

## [0.3.54](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.53...freeciv3d-v0.3.54) (2026-02-15)


### Bug Fixes

* **ci:** remove automatic release trigger from production deploy ([#150](https://github.com/taso-ventures/freeciv3d/issues/150)) ([2355d6f](https://github.com/taso-ventures/freeciv3d/commit/2355d6fb74ec7212fc8b88bfe74a587221843ff2))
* **gateway:** stop_game works for WS-originated games ([#153](https://github.com/taso-ventures/freeciv3d/issues/153)) ([39d58d4](https://github.com/taso-ventures/freeciv3d/commit/39d58d4eda96d38148e3cb96a92472005e971668))

## [0.3.53](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.52...freeciv3d-v0.3.53) (2026-02-13)


### Features

* **proxy,gateway:** REST fallback for force_end_turn + turn desync fixes ([#146](https://github.com/taso-ventures/freeciv3d/issues/146)) ([c8a2a19](https://github.com/taso-ventures/freeciv3d/commit/c8a2a19695894f23b4096e78c4f9d988c400aceb))
* **proxy:** support tiny maps, fix E235 sanitizer bug, harden input validation ([#149](https://github.com/taso-ventures/freeciv3d/issues/149)) ([788b793](https://github.com/taso-ventures/freeciv3d/commit/788b793f7ad2e699ba982399810cbef3d36d6637))


### Bug Fixes

* upgrade puppeteer to resolve tar-fs and ws security vulnerabilities ([#147](https://github.com/taso-ventures/freeciv3d/issues/147)) ([fd18e6d](https://github.com/taso-ventures/freeciv3d/commit/fd18e6d29d4986f8606e550453de7355cf51cbb8))

## [0.3.52](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.51...freeciv3d-v0.3.52) (2026-02-11)


### Features

* **gateway:** authoritative global state via observer CivCom + REST endpoint ([#142](https://github.com/taso-ventures/freeciv3d/issues/142)) ([5bb51cf](https://github.com/taso-ventures/freeciv3d/commit/5bb51cf9a67ed25b02d19dafa1c5c72d27904d3c))

## [0.3.51](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.50...freeciv3d-v0.3.51) (2026-02-11)


### Bug Fixes

* **proxy:** disable autotoggle on pause and add dead CivCom TTL cleanup ([#143](https://github.com/taso-ventures/freeciv3d/issues/143)) ([01f209b](https://github.com/taso-ventures/freeciv3d/commit/01f209b57aeb98c0637781ed737ba344191720b5))

## [0.3.50](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.49...freeciv3d-v0.3.50) (2026-02-09)


### Bug Fixes

* prevent game state loss on pod restart and recovery death spiral ([#140](https://github.com/taso-ventures/freeciv3d/issues/140)) ([447df62](https://github.com/taso-ventures/freeciv3d/commit/447df62dd628dabae5a53d3005d01ec27230974d))

## [0.3.49](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.48...freeciv3d-v0.3.49) (2026-02-09)


### Bug Fixes

* **proxy:** treat expected_turn=0 as unknown and increase drift tolerance to ±5 ([#138](https://github.com/taso-ventures/freeciv3d/issues/138)) ([9124a70](https://github.com/taso-ventures/freeciv3d/commit/9124a70744bb6afb3a27a59ffc14116fad3bae85))

## [0.3.48](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.47...freeciv3d-v0.3.48) (2026-02-07)


### Bug Fixes

* **gateway:** prevent stale CivCom registry poisoning causing unit-not-found ([#136](https://github.com/taso-ventures/freeciv3d/issues/136)) ([2ac2933](https://github.com/taso-ventures/freeciv3d/commit/2ac2933b3266148070442b5071d54b0d4fbe8a8d))

## [0.3.47](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.46...freeciv3d-v0.3.47) (2026-02-06)


### Bug Fixes

* **gateway:** prevent proxy reconnection race condition ([#134](https://github.com/taso-ventures/freeciv3d/issues/134)) ([9b019b6](https://github.com/taso-ventures/freeciv3d/commit/9b019b66478a46702dcf1eb9469cea33d785171c))

## [0.3.46](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.45...freeciv3d-v0.3.46) (2026-02-05)


### Bug Fixes

* unblock agent reconnection fields ([#133](https://github.com/taso-ventures/freeciv3d/issues/133)) ([3576874](https://github.com/taso-ventures/freeciv3d/commit/3576874d0ea6870d7fedf96459f4fee2b0f06eeb))


### Miscellaneous

* Add Claude Code GitHub Workflow ([#131](https://github.com/taso-ventures/freeciv3d/issues/131)) ([2d6e9f1](https://github.com/taso-ventures/freeciv3d/commit/2d6e9f1d04074df453ab9d396f3bf590539735e9))

## [0.3.45](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.44...freeciv3d-v0.3.45) (2026-02-05)


### Features

* add terrain_ready event for iframe loading communication ([#129](https://github.com/taso-ventures/freeciv3d/issues/129)) ([bcf7edd](https://github.com/taso-ventures/freeciv3d/commit/bcf7edddb958b9fe3ab19645ea1053928ac98c9f))

## [0.3.44](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.43...freeciv3d-v0.3.44) (2026-02-02)


### Bug Fixes

* stop forwarding packets to dead WebSocket connections ([#127](https://github.com/taso-ventures/freeciv3d/issues/127)) ([6298f87](https://github.com/taso-ventures/freeciv3d/commit/6298f87fea00d90058ee35d64380762c0e899bea))

## [0.3.43](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.42...freeciv3d-v0.3.43) (2026-02-02)


### Bug Fixes

* restore immediate observer centering when units found ([#125](https://github.com/taso-ventures/freeciv3d/issues/125)) ([dd53421](https://github.com/taso-ventures/freeciv3d/commit/dd534218d2c52e879b0f372ff24fb356eb713ba8))

## [0.3.42](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.41...freeciv3d-v0.3.42) (2026-02-02)


### Bug Fixes

* settler movement and observer code cleanup ([#123](https://github.com/taso-ventures/freeciv3d/issues/123)) ([0a7a419](https://github.com/taso-ventures/freeciv3d/commit/0a7a4198a0daecd2a1b84e2aba60fee8ee9fb471))

## [0.3.41](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.40...freeciv3d-v0.3.41) (2026-02-01)


### Features

* add auto-zoom global view for observers ([#121](https://github.com/taso-ventures/freeciv3d/issues/121)) ([ab5cb3a](https://github.com/taso-ventures/freeciv3d/commit/ab5cb3adca6b417bfb3283b2b236e3df2f900452))

## [0.3.40](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.39...freeciv3d-v0.3.40) (2026-02-01)


### Bug Fixes

* settlers spawn with full movement points on valid terrain ([#119](https://github.com/taso-ventures/freeciv3d/issues/119)) ([8156ed6](https://github.com/taso-ventures/freeciv3d/commit/8156ed661ed8e148e2d83b206a9db9c9dd0c1448))

## [0.3.39](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.38...freeciv3d-v0.3.39) (2026-02-01)


### Bug Fixes

* scale to single replica to fix observer routing to wrong pod ([#117](https://github.com/taso-ventures/freeciv3d/issues/117)) ([aa29021](https://github.com/taso-ventures/freeciv3d/commit/aa290217636c97cb3851959d80280b2cc8b23605))

## [0.3.38](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.37...freeciv3d-v0.3.38) (2026-02-01)


### Bug Fixes

* add production name fuzzy matching and remove connection delays ([#115](https://github.com/taso-ventures/freeciv3d/issues/115)) ([d6bce3a](https://github.com/taso-ventures/freeciv3d/commit/d6bce3ab40fc6f93fde55b9d23b6daa5e66617bb))

## [0.3.37](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.36...freeciv3d-v0.3.37) (2026-02-01)


### Bug Fixes

* prevent observer black screen with immediate notification and fallback centering ([#113](https://github.com/taso-ventures/freeciv3d/issues/113)) ([f3003f8](https://github.com/taso-ventures/freeciv3d/commit/f3003f881c71010324aad6dd3154a3995f5d8a91))

## [0.3.36](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.35...freeciv3d-v0.3.36) (2026-02-01)


### Bug Fixes

* observer black screen, turn limit enforcement, and iframe notifications ([#111](https://github.com/taso-ventures/freeciv3d/issues/111)) ([f44e77e](https://github.com/taso-ventures/freeciv3d/commit/f44e77e173d1158c9b8c8508f3b60180147c2f0d))

## [0.3.35](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.34...freeciv3d-v0.3.35) (2026-01-31)


### Bug Fixes

* resolve observer black tiles regression from e8e653c ([#109](https://github.com/taso-ventures/freeciv3d/issues/109)) ([499527f](https://github.com/taso-ventures/freeciv3d/commit/499527ff131e26f33280cd4c3c76633b4788a8a9))

## [0.3.34](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.33...freeciv3d-v0.3.34) (2026-01-30)


### Bug Fixes

* resolve observer iframe connection issues (6 fixes) ([#107](https://github.com/taso-ventures/freeciv3d/issues/107)) ([2aa5d66](https://github.com/taso-ventures/freeciv3d/commit/2aa5d66539f7b83311e7a9e862863ca446429d96))

## [0.3.33](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.32...freeciv3d-v0.3.33) (2026-01-30)


### Bug Fixes

* resolve production cascading failures (6 issues) ([#106](https://github.com/taso-ventures/freeciv3d/issues/106)) ([7f7f382](https://github.com/taso-ventures/freeciv3d/commit/7f7f38216b9696e6f8f9fc0c3c3045c2b87cdf55))
* resolve production cascading failures and add endgame handling ([1833b57](https://github.com/taso-ventures/freeciv3d/commit/1833b577cbc701461e78319cf1dbd66f933136af))

## [0.3.32](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.31...freeciv3d-v0.3.32) (2026-01-29)


### Bug Fixes

* resolve combat action coordinate formats and use FAIR generator ([#103](https://github.com/taso-ventures/freeciv3d/issues/103)) ([6da6300](https://github.com/taso-ventures/freeciv3d/commit/6da6300f0adeb36661d755b31a2a422d3e1cd8a8))

## [0.3.31](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.30...freeciv3d-v0.3.31) (2026-01-29)


### Bug Fixes

* prevent zombie sessions and port allocation exhaustion ([#101](https://github.com/taso-ventures/freeciv3d/issues/101)) ([6f7d273](https://github.com/taso-ventures/freeciv3d/commit/6f7d273ed75a1005c988f3144dc11bfe3f6f98f7))

## [0.3.30](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.29...freeciv3d-v0.3.30) (2026-01-29)


### Bug Fixes

* E142 mid-game reconnection and staggered observer connections ([#99](https://github.com/taso-ventures/freeciv3d/issues/99)) ([1f7b5e1](https://github.com/taso-ventures/freeciv3d/commit/1f7b5e109eea3d3513651fba518b91d72407668b))

## [0.3.29](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.28...freeciv3d-v0.3.29) (2026-01-29)


### Bug Fixes

* Increase observer connection limits for 5000+ concurrent viewers ([#97](https://github.com/taso-ventures/freeciv3d/issues/97)) ([052b093](https://github.com/taso-ventures/freeciv3d/commit/052b093e31dc2822f08465109e23153a3c635c28))

## [0.3.28](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.27...freeciv3d-v0.3.28) (2026-01-28)


### Bug Fixes

* Resolve observer timeouts and OpenTelemetry TLS misconfiguration ([#95](https://github.com/taso-ventures/freeciv3d/issues/95)) ([a9f1927](https://github.com/taso-ventures/freeciv3d/commit/a9f192775ce5785ba7028d1ffd74f5d8393b27b9))

## [0.3.27](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.26...freeciv3d-v0.3.27) (2026-01-28)


### Bug Fixes

* **observer:** Use LOG_NORMAL instead of undefined LOG_WARN ([efe082a](https://github.com/taso-ventures/freeciv3d/commit/efe082a5862a3afbad8fc2cb3f12f8b127ebcf36))

## [0.3.26](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.25...freeciv3d-v0.3.26) (2026-01-28)


### Bug Fixes

* **observer:** Make global observer connect last to avoid civserver race condition ([2225dc8](https://github.com/taso-ventures/freeciv3d/commit/2225dc8ed5a79b3e15fd4d331e52f8a58b78e257))
* Resolve observer race condition causing black terrain in multi-observer views ([#93](https://github.com/taso-ventures/freeciv3d/issues/93)) ([d29536f](https://github.com/taso-ventures/freeciv3d/commit/d29536ff27c70d580232a790b79eff15ef72f8c5))

## [0.3.25](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.24...freeciv3d-v0.3.25) (2026-01-28)


### Bug Fixes

* **proxy:** Resolve observer race condition causing black terrain in multi-observer views ([6adf7c6](https://github.com/taso-ventures/freeciv3d/commit/6adf7c608ff16096a3448dbcf169665334fa90e0))

## [0.3.24](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.23...freeciv3d-v0.3.24) (2026-01-27)


### Features

* Scale WebSocket connections for 1000+ concurrent viewers ([#89](https://github.com/taso-ventures/freeciv3d/issues/89)) ([c50db5e](https://github.com/taso-ventures/freeciv3d/commit/c50db5ee0d30388b6507122819512cd76db0a2a8))

## [0.3.23](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.22...freeciv3d-v0.3.23) (2026-01-27)


### Bug Fixes

* **AGE-312:** [freeciv-proxy] resolve gameplay turn failures; add local moves tracking ([#86](https://github.com/taso-ventures/freeciv3d/issues/86)) ([98712fe](https://github.com/taso-ventures/freeciv3d/commit/98712fe86586d6bc38da1d815cacdbdc943cdaf9))

## [0.3.22](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.21...freeciv3d-v0.3.22) (2026-01-27)


### Bug Fixes

* Resolve observer race condition causing black terrain in multi-observer views ([#85](https://github.com/taso-ventures/freeciv3d/issues/85)) ([e8e653c](https://github.com/taso-ventures/freeciv3d/commit/e8e653cbc1beedb756836c7be924430b7e4bac03))

## [0.3.21](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.20...freeciv3d-v0.3.21) (2026-01-26)


### Bug Fixes

* **proxy:** production field pipeline cleanup, spaceship/wonder tracking, and debug logging removal ([#81](https://github.com/taso-ventures/freeciv3d/issues/81)) ([f246839](https://github.com/taso-ventures/freeciv3d/commit/f246839c3ddf623984e8236d05c989157c8fbe96))

## [0.3.20](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.19...freeciv3d-v0.3.20) (2026-01-25)


### Bug Fixes

* Observer mode regression and P3 display black terrain ([#82](https://github.com/taso-ventures/freeciv3d/issues/82)) ([b70b023](https://github.com/taso-ventures/freeciv3d/commit/b70b0234dbe1bf8d4682576c2fb83662b6de9419))

## [0.3.19](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.18...freeciv3d-v0.3.19) (2026-01-24)


### Bug Fixes

* **proxy:** Resolve match start failures with time module and port allocation fixes ([#79](https://github.com/taso-ventures/freeciv3d/issues/79)) ([a647395](https://github.com/taso-ventures/freeciv3d/commit/a647395a5db1aef4c2537deb1b29dcc7043a8fe2))

## [0.3.18](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.17...freeciv3d-v0.3.18) (2026-01-23)


### Features

* **k8s:** Add production readiness for 500-user beta launch ([#77](https://github.com/taso-ventures/freeciv3d/issues/77)) ([1a517d8](https://github.com/taso-ventures/freeciv3d/commit/1a517d8950e1b0a52781589310cef506dc4d3eed))

## [0.3.17](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.16...freeciv3d-v0.3.17) (2026-01-22)


### Bug Fixes

* **proxy:** Prevent mid-game reconnection failures (E142 + E120) ([#75](https://github.com/taso-ventures/freeciv3d/issues/75)) ([f4c9b85](https://github.com/taso-ventures/freeciv3d/commit/f4c9b85a70e5cea5cdec21b7b026bffa41aa274a))

## [0.3.16](https://github.com/taso-ventures/freeciv3d/compare/freeciv3d-v0.3.15...freeciv3d-v0.3.16) (2026-01-22)


### Bug Fixes

* Chrome black tiles, WebSocket resilience, and K8s observability ([#72](https://github.com/taso-ventures/freeciv3d/issues/72)) ([44fba21](https://github.com/taso-ventures/freeciv3d/commit/44fba21b7ace038a453510b31df331f6c9ed692d))
* **k8s:** Add GATEWAY_REDIS_URL env var to fciv-net deployment ([#74](https://github.com/taso-ventures/freeciv3d/issues/74)) ([a04109f](https://github.com/taso-ventures/freeciv3d/commit/a04109fadea65e07a03bfecf32353c04894be4c1))


### Documentation

* **docker:** Document Redis trusted network security assumption ([8fe596a](https://github.com/taso-ventures/freeciv3d/commit/8fe596a99017d4c6728d8f97f4acc524d443a407))

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
