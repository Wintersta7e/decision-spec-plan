# Changelog

## [1.3.1](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.3.0...v1.3.1) (2026-11-14)


### Bug Fixes

* **tests:** lower the git floor in the session-interference test ([4f9242f](https://github.com/Wintersta7e/decision-spec-plan/commit/4f9242fd6ff73967d7a9731ae9852666991ebb08))
* **tests:** skip the repo-doc checks outside a checkout ([06d1fdc](https://github.com/Wintersta7e/decision-spec-plan/commit/06d1fdc5eb6c5bf600e04c7f6cbe4c53c9de419a))

## [1.3.0](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.2.0...v1.3.0) (2026-11-13)


### Features

* **dsp-monitor:** add ended runs, run detail and keyboard shortcuts ([41afe61](https://github.com/Wintersta7e/decision-spec-plan/commit/41afe61ccdd903e31cb91917c3e6e0c48fbecf73))
* **dsp-monitor:** add the loopback monitor server and its page skeleton ([25e171b](https://github.com/Wintersta7e/decision-spec-plan/commit/25e171b55bddb14e5dce237103965e8f5e3dfe7f))
* **dsp-monitor:** add the monitor page shell and overview ([3bd923a](https://github.com/Wintersta7e/decision-spec-plan/commit/3bd923a38eb0a6255a9bd6683dc103f8285018e3))
* **dsp-monitor:** discover routes and runs from registry and markers ([941c41f](https://github.com/Wintersta7e/decision-spec-plan/commit/941c41f87eef0e618bc38d005610750f2756c8e1))
* **dsp-monitor:** draw state icons as inline SVG ([060cd94](https://github.com/Wintersta7e/decision-spec-plan/commit/060cd94a7e5eb90e75768859a1753ce64caba1b1))
* **dsp-monitor:** find a free port and detect a running monitor ([edd2349](https://github.com/Wintersta7e/decision-spec-plan/commit/edd2349ce3200c1853673d4baa5559f9fde00999))
* **dsp-monitor:** fold the event logs into agent and recording state ([9b0357f](https://github.com/Wintersta7e/decision-spec-plan/commit/9b0357f54397753e36478076b41583405d4e27fe))
* **dsp-monitor:** raise waiting and attention items ([6f87910](https://github.com/Wintersta7e/decision-spec-plan/commit/6f879105bed1ccfd05f27260c3c853cce16a4d1c))
* **dsp-monitor:** refresh reports under per-route limits and deadlines ([6aa353f](https://github.com/Wintersta7e/decision-spec-plan/commit/6aa353fed591da852e58900c3676095704ef4a23))
* **dsp-monitor:** serve the full v1 state and run detail ([ee89b37](https://github.com/Wintersta7e/decision-spec-plan/commit/ee89b37023a9736d5d767d08c902e8b51e2ccef4))
* **dsp-monitor:** show a route's stages, lanes, wave graph and agents ([e4be5d9](https://github.com/Wintersta7e/decision-spec-plan/commit/e4be5d95fa3cb3b2e00cdf4e587f6ead3118f571))
* **dsp-route,hooks:** record TaskStop targets and AskUserQuestion calls ([9e4e5dc](https://github.com/Wintersta7e/decision-spec-plan/commit/9e4e5dc13aa4883318f1c108b218fa22c1c7dec7))
* **dsp-route:** add the monitor switch read from DSP_MONITOR ([904961c](https://github.com/Wintersta7e/decision-spec-plan/commit/904961c6406210822bdd961f33b97a9c8c57ec80))
* **dsp-route:** add the per-session event recorder ([be2cc44](https://github.com/Wintersta7e/decision-spec-plan/commit/be2cc446b2f946084ea23e49aef452f35451c26a))
* **dsp-route:** add the stage strip and wave edges to report data ([f8c4f46](https://github.com/Wintersta7e/decision-spec-plan/commit/f8c4f46538ac22f22dab4e4edb01e69345e044d9))
* **dsp-route:** bound git calls by a per-context deadline ([fd7cb48](https://github.com/Wintersta7e/decision-spec-plan/commit/fd7cb48938ee9473dbc86a6741a4fd13ed868f1f))
* **dsp-route:** give each route run an id kept across activations ([cb661d3](https://github.com/Wintersta7e/decision-spec-plan/commit/cb661d37c4295460b3702157789b668b56559511))
* **dsp-route:** keep a session's earlier routes in its registry entry ([cdf6d2f](https://github.com/Wintersta7e/decision-spec-plan/commit/cdf6d2fb44008909e2eed43f036e85cddd234538))
* **dsp-route:** record a routed session's hook events when enabled ([5394a9c](https://github.com/Wintersta7e/decision-spec-plan/commit/5394a9c0fae46ed2dcd4ffdb7a117030868ed857))
* **dsp-route:** return the route report as data before rendering it ([0ae9db2](https://github.com/Wintersta7e/decision-spec-plan/commit/0ae9db2464530925abdd06cd33c766950bdd8b1d))
* **hooks,dsp-route:** register the guarded recording hooks ([d3722ed](https://github.com/Wintersta7e/decision-spec-plan/commit/d3722edad01720df74399b7d2903686fea2a22a0))


### Bug Fixes

* **dsp-monitor:** show 24-hour times and a blocked glyph every font has ([b93330c](https://github.com/Wintersta7e/decision-spec-plan/commit/b93330c0b181a8008177e715b7ab06dfdfbf80da))
* **dsp-monitor:** time refresh intervals on the monotonic clock ([2c557d9](https://github.com/Wintersta7e/decision-spec-plan/commit/2c557d9a1d77ad6939477c8a9d6ade9d1a7bc03d))
* **dsp-monitor:** use label glyphs every font draws ([e1fec14](https://github.com/Wintersta7e/decision-spec-plan/commit/e1fec1440c877915bac618d1ee46868823f74ff5))
* **dsp-route,gate:** run git without optional locks ([016d68e](https://github.com/Wintersta7e/decision-spec-plan/commit/016d68efb03d77a1f61ed6ea24de514038bb667b))
* **dsp-route:** claim the hook's throttle window atomically ([a308169](https://github.com/Wintersta7e/decision-spec-plan/commit/a30816909b370b687e0a345051d83262c82270d4))
* **dsp-route:** keep the injected report per session ([e32d159](https://github.com/Wintersta7e/decision-spec-plan/commit/e32d1592fb57a839e939a3daef96dddb943721ff))
* **dsp-route:** replace the marker and entry atomically in the hook ([59a2138](https://github.com/Wintersta7e/decision-spec-plan/commit/59a2138c67e0509e06e10096077840c61649df46))
* **dsp-route:** retry the event-log lock in 50 short attempts ([407a42b](https://github.com/Wintersta7e/decision-spec-plan/commit/407a42b0531f99bc021daf0af40df91e91735a12))
* **record,docs:** stop recording free-text event fields ([c8bb84d](https://github.com/Wintersta7e/decision-spec-plan/commit/c8bb84da402af582c3ae9f8285cdeef301d40442))
* **scope-check,test-check:** accept only a revision range for --diff ([e513dfd](https://github.com/Wintersta7e/decision-spec-plan/commit/e513dfd8853a37c8cae9759c61c379aa270defa6))
* **tests:** count the recorder's lock give-ups in the parallel test ([d123ff2](https://github.com/Wintersta7e/decision-spec-plan/commit/d123ff25854f3b1790d73fbefaead88bbad6c662))
* **tests:** time the monitor probe on the monotonic clock ([43ff719](https://github.com/Wintersta7e/decision-spec-plan/commit/43ff719e0872311c577527fc1cfb81600027ec3c))
* **usage-report,dsp-route:** count hooks of a lead outside its repo ([b8b170b](https://github.com/Wintersta7e/decision-spec-plan/commit/b8b170bf977356a7a36e4e4792162e6bde42c824))
* **usage-report,dsp-route:** count hooks of removed in-repo worktrees ([1498fcb](https://github.com/Wintersta7e/decision-spec-plan/commit/1498fcb372d88982b2100ee12390aa05052774a2))


### Performance Improvements

* **dsp-route,route-state:** cache the lanes proven merged ([7eda512](https://github.com/Wintersta7e/decision-spec-plan/commit/7eda512dd4cfb38880d48a7333c0d7e0bc354623))
* **dsp-route:** load shutil only when git runs ([0881521](https://github.com/Wintersta7e/decision-spec-plan/commit/08815218811ff734a00c230e1000e9126767239e))

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
