# Changelog

## [1.2.0](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.1.3...v1.2.0) (2026-11-12)


### Features

* **decision-check:** require a review's Coverage of each changed file ([634ac46](https://github.com/Wintersta7e/decision-spec-plan/commit/634ac46ff12900c8246f8e0501d1319bf9584603))
* **route-state:** hold a review comment while its Coverage fails ([5d78771](https://github.com/Wintersta7e/decision-spec-plan/commit/5d787711376ade05c1e88d25d0c18ce8f7ed0965))
* **route-state:** hold a review submitted with no review on record ([c7ccc7e](https://github.com/Wintersta7e/decision-spec-plan/commit/c7ccc7e5322627a427f5eb59eb44855aa2ab26fd))

## [1.1.3](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.1.2...v1.1.3) (2026-11-11)


### Bug Fixes

* **route-state:** report a skill file as changed only when its text is ([ee66d17](https://github.com/Wintersta7e/decision-spec-plan/commit/ee66d17f3e6b6adae5c27e83a8d7df6a11551680))

## [1.1.2](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.1.1...v1.1.2) (2026-11-11)


### Performance Improvements

* **route-state:** batch lane git calls and cache patch checks ([84f480c](https://github.com/Wintersta7e/decision-spec-plan/commit/84f480c552c01edc3d153255ae1d95b363ba2510))

## [1.1.1](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.1.0...v1.1.1) (2026-11-11)


### Bug Fixes

* **release:** drop the CI dispatch that failed the release run ([ca7dbef](https://github.com/Wintersta7e/decision-spec-plan/commit/ca7dbef817b36e43f274556673755a2bbea5bcbf))

## [1.1.0](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.0.0...v1.1.0) (2026-11-11)


### Features

* **gate,push-guard:** run gates through gate.py and check in pre-push ([1198840](https://github.com/Wintersta7e/decision-spec-plan/commit/1198840aefebdec0fc61009ff20f8b2c6482fb50))
* **plan-lint,route-state:** plan each gate's minutes and where it runs ([3c70cb6](https://github.com/Wintersta7e/decision-spec-plan/commit/3c70cb6cf541d9a6371051a0009029821019c8f2))
* **route-state,decision-check:** tie decisions to asks, price waves ([1893b63](https://github.com/Wintersta7e/decision-spec-plan/commit/1893b63b03e65c5055fc233cad84f5fbae3582a9))
* **route-state:** hold a moved base until the user picks how to follow ([57ddf73](https://github.com/Wintersta7e/decision-spec-plan/commit/57ddf732fa62239eca8935190d8812116d405ea0))
* **route-state:** refuse a hand-written gate log and name each hold ([22886fe](https://github.com/Wintersta7e/decision-spec-plan/commit/22886fea68055a388262d4dc551e13c94cb475ab))
* **scope-check,route-state:** check asks both ways and fence publishes ([bd68a48](https://github.com/Wintersta7e/decision-spec-plan/commit/bd68a4832678c8182ecf8b9abbbe836054910325))
* **test-check,route-state:** hold a lane merge that tests less ([89c618f](https://github.com/Wintersta7e/decision-spec-plan/commit/89c618f8aac8527d175195eeee788087989793bb))


### Bug Fixes

* **agents,route-state,usage-report:** wait under the cache's 5 minutes ([7e5f6d5](https://github.com/Wintersta7e/decision-spec-plan/commit/7e5f6d5f1913e2f727ceabc275af82c8beeb9e87))
* **apply-markers:** re-run, fence, line-ending and BOM safety ([b79219d](https://github.com/Wintersta7e/decision-spec-plan/commit/b79219de71623971547a2095c0ccd59838f7f85a))
* **criteria-check:** read bold-code table ids and colocated tests ([52f3c19](https://github.com/Wintersta7e/decision-spec-plan/commit/52f3c19e394d4a0453ca7d144434a74443febc5a))
* **decision-check:** read verdicts, SETTLED bases and findings whole ([78ab98f](https://github.com/Wintersta7e/decision-spec-plan/commit/78ab98f22477ce8482bb25d4e20496e2eb212de1))
* **dsp-route:** find monitor output under the configured temp root ([36587ab](https://github.com/Wintersta7e/decision-spec-plan/commit/36587abba3a04eba9ab4aa9a7394f3b2dcf7f545))
* **dsp-route:** hold gate-log writes through doubled slashes ([0a8518b](https://github.com/Wintersta7e/decision-spec-plan/commit/0a8518b17ae18baed2fded61278a2e91a1681308))
* **gate:** mark gate.py executable like the other scripts ([ff61505](https://github.com/Wintersta7e/decision-spec-plan/commit/ff615057a458f41a054f5a53606ea65037f9978c))
* **push-guard,shell-cmd,route-state:** read commands as bash does ([9d125af](https://github.com/Wintersta7e/decision-spec-plan/commit/9d125afae9b97796adc14284cd3b88a91a03f235))
* **push-guard,shell-cmd:** hold what a command runs, not its words ([eacaf45](https://github.com/Wintersta7e/decision-spec-plan/commit/eacaf45562ebadd33bc670c3db8e1d90bfefca26))
* **push-guard,shell-cmd:** read bypasses the shell sets, not mentions ([eb631d8](https://github.com/Wintersta7e/decision-spec-plan/commit/eb631d84c82135d945aeafb8fdbafba100c8be5c))
* **push-guard:** ask the user before a push skips the guard ([0d9f354](https://github.com/Wintersta7e/decision-spec-plan/commit/0d9f354444d38062df861b9a731dfb5c5f85d906))
* read plans, criteria and markers the way authors write them ([b920898](https://github.com/Wintersta7e/decision-spec-plan/commit/b9208987a81c82faaed78b29446db46d49f3f98f))
* **route-state,push-guard,shell-cmd,usage-report:** harden the hooks ([c904924](https://github.com/Wintersta7e/decision-spec-plan/commit/c9049247c0e1cb674a2f42d3bf0c546cc1c3c46b))
* **route-state,push-guard,usage-report:** fix what live sessions hit ([c63fe6d](https://github.com/Wintersta7e/decision-spec-plan/commit/c63fe6d67d6a7e3916db3a837f0f6ccc6cc2294b))
* **route-state,usage-report:** count only what each check is about ([680e209](https://github.com/Wintersta7e/decision-spec-plan/commit/680e20962a78548f2948a75f2fbdbb3ad121d0e5))
* **route-state:** catch publishes past options or with a computed verb ([bedf350](https://github.com/Wintersta7e/decision-spec-plan/commit/bedf350dd4af704aec8b5132389214df6aac8561))
* **route-state:** close four more ways past the publish check ([3b9c8bf](https://github.com/Wintersta7e/decision-spec-plan/commit/3b9c8bf2cca6e90aaf2cdeaf2e7861d64a95ab8e))
* **route-state:** close two ways past the route budget hold ([d953291](https://github.com/Wintersta7e/decision-spec-plan/commit/d9532914db7dbcf0cb5e1836997164d8c7c5d379))
* **route-state:** count only the wave's agents against its budget ([cc0e7c2](https://github.com/Wintersta7e/decision-spec-plan/commit/cc0e7c2a084edbdd980706757532f501399b177d))
* **route-state:** hold one budget per route, kept across lead sessions ([2ba9210](https://github.com/Wintersta7e/decision-spec-plan/commit/2ba9210e159be2c9217d628bf01dbc1ddf641819))
* **route-state:** read push outputs and gradle tasks as the tools do ([ef3458d](https://github.com/Wintersta7e/decision-spec-plan/commit/ef3458dc8e3c9b73331cd2b6337ec9469f8f4032))
* **route-state:** refuse a message to an agent whose run ended ([c79004a](https://github.com/Wintersta7e/decision-spec-plan/commit/c79004a395a3b0e892c61a9faa35d0a0883d498a))
* **route-state:** tell the lead when it edits the repository itself ([497fbe4](https://github.com/Wintersta7e/decision-spec-plan/commit/497fbe463d33c5262a3ce377f1659d086b39e6b9))
* **scope-check:** check .mts, .cts, .adoc and .puml rows for an ask ([9085996](https://github.com/Wintersta7e/decision-spec-plan/commit/9085996d463c2513405488d6101eb4e809311608))
* **scope-check:** read all-of-wave deps, extensionless files, plan ids ([f14e8a0](https://github.com/Wintersta7e/decision-spec-plan/commit/f14e8a092bf700e59c5261783f7954bbef910947))
* **scope-check:** read every plan row in --diff, not only --ext files ([90c9559](https://github.com/Wintersta7e/decision-spec-plan/commit/90c9559211afcd5efd2a6db295cfaf9a872ebf78))
* **test-check:** count what a lane takes from tests it keeps ([5c11052](https://github.com/Wintersta7e/decision-spec-plan/commit/5c11052f879956a044109217b3b64b7d4da3f7d9))
* **transcript:** count no job from a repeated api-request-blob result ([0aff111](https://github.com/Wintersta7e/decision-spec-plan/commit/0aff111f341fde455f9da89fc2ce1fbc8db2745b))

## Changelog
