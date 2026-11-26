# Changelog

## [1.6.0](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.5.0...v1.6.0) (2026-11-26)


### Features

* **route-state:** flag verdict findings routed to no fix task ([8645ddc](https://github.com/Wintersta7e/decision-spec-plan/commit/8645ddc6fc100f716d38790d7c843f32ad577ce5))
* **route-state:** retire route markers with --end ([60e3a13](https://github.com/Wintersta7e/decision-spec-plan/commit/60e3a133a20bcd72a781c5566fc8c45c20db891a))


### Bug Fixes

* **agents:** run the mechanical tier at high effort ([5a7900c](https://github.com/Wintersta7e/decision-spec-plan/commit/5a7900c7719b5de2eb44ddb8eb937d0a1ffdadea))
* **route-state:** check inline and relative handed commands ([f5944dc](https://github.com/Wintersta7e/decision-spec-plan/commit/f5944dcfb7a9c24cf4a83b3f6a76a9670855c0b9))
* **route-state:** count a route's budget from its first record ([0254251](https://github.com/Wintersta7e/decision-spec-plan/commit/025425131f10da5b885fb7780a6c84172a291439))
* **route-state:** count recommendation answers in this run only ([95d59e3](https://github.com/Wintersta7e/decision-spec-plan/commit/95d59e35901c9caa9d58622d9ac1478882553973))
* **route-state:** deny an agent when the outward check fails ([2a3192e](https://github.com/Wintersta7e/decision-spec-plan/commit/2a3192eda3261d687921017ac8fc33d4ea79d8e0))
* **route-state:** fail closed on unread shell bodies and parse errors ([d42d837](https://github.com/Wintersta7e/decision-spec-plan/commit/d42d8373aa194ee6e4cbac8aef1eaaa72df56093))
* **route-state:** give a green lane with tasks left its next group ([b767ef4](https://github.com/Wintersta7e/decision-spec-plan/commit/b767ef4035d99a06476027b17eb4d78cd03fd703))
* **route-state:** hold a publisher run through an inert run form ([8af1edb](https://github.com/Wintersta7e/decision-spec-plan/commit/8af1edb6463c887b0906c7a9394d35fae64155c6))
* **route-state:** hold computed eval and shell bodies, tighten uv list ([6ef037c](https://github.com/Wintersta7e/decision-spec-plan/commit/6ef037c64cfef5fba062392ac645636bb6df913e))
* **route-state:** hold the lead's third repo edit everywhere, Bash too ([e4a86eb](https://github.com/Wintersta7e/decision-spec-plan/commit/e4a86eb50266cf212e053baa0f29749e82a4f64d))
* **route-state:** ignore remote-tracking refs in the fingerprint ([938d051](https://github.com/Wintersta7e/decision-spec-plan/commit/938d0517aca454a89b3d392ee0135bef628f69bd))
* **route-state:** keep a pushed remote ref in the fingerprint ([dcd8754](https://github.com/Wintersta7e/decision-spec-plan/commit/dcd875411220f90ec017755ba1394bd06860af01))
* **route-state:** load the route only when the user asks to run it ([dfffa33](https://github.com/Wintersta7e/decision-spec-plan/commit/dfffa335e06f4b37b7648b13647130ab18f3a5f3))
* **route-state:** number asks per route, skipping peer and limit prompts ([ba9eafd](https://github.com/Wintersta7e/decision-spec-plan/commit/ba9eafd0f9a0d723ec56187fa76377b3865fe98f))
* **route-state:** pass local cargo, uv, npm-run and docker reads ([3eab76c](https://github.com/Wintersta7e/decision-spec-plan/commit/3eab76cede50e702016305b92f3bac9a03c04482))
* **route-state:** read eval and shell bodies only where they run ([8131b8b](https://github.com/Wintersta7e/decision-spec-plan/commit/8131b8bc93993746fafee96df9e5b7e9afdd0dd0))
* **test-check:** pass an edited test the plan names ([8ade64c](https://github.com/Wintersta7e/decision-spec-plan/commit/8ade64c3c00411d53aff256261e6e46f64d5082d))

## [1.5.0](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.4.0...v1.5.0) (2026-11-19)


### Features

* **route-state:** fingerprint the hunted repository ([52bd4ad](https://github.com/Wintersta7e/decision-spec-plan/commit/52bd4ad6b33d8b47882f2328f4320eb0b5d2ae45))
* **route-state:** hold a hunt's dispatch to the route's budget ([34693fc](https://github.com/Wintersta7e/decision-spec-plan/commit/34693fc84de83896827781c37ef474897591d8b6))
* **route-state:** hold a hunter's commit, git config and repo edits ([9c2410d](https://github.com/Wintersta7e/decision-spec-plan/commit/9c2410d511bc09029df805eb4b8954dd640a7263))
* **route-state:** run a hunter's shell with the hunted repo read-only ([847f63e](https://github.com/Wintersta7e/decision-spec-plan/commit/847f63eae5a330f5979d0db92749e114f2150f35))


### Bug Fixes

* **route-state:** bind no variable when the command may set any ([341d381](https://github.com/Wintersta7e/decision-spec-plan/commit/341d381afd8225b966633f5b5cd9939c4a938e68))
* **route-state:** close the hunter boundary's config and lookup gaps ([1bc74ba](https://github.com/Wintersta7e/decision-spec-plan/commit/1bc74ba46f4c2c5414bc04e3f4bd9064d81eb146))
* **route-state:** give a hunter read-only git inside the hunted repo ([c8fe8cc](https://github.com/Wintersta7e/decision-spec-plan/commit/c8fe8cc2c83b2fcbfe813957f7cf2b14d0f37f13))
* **route-state:** hold a hunter's git pointed at another repository ([f8a7727](https://github.com/Wintersta7e/decision-spec-plan/commit/f8a7727c7dbdda6699fcadd1c0135f9af451c858))
* **route-state:** hold a hunter's git that may point at another repo ([9597e84](https://github.com/Wintersta7e/decision-spec-plan/commit/9597e8436f43c9f9e404f24b8d4e405cec9ca907))
* **route-state:** hold hunter plumbing commits and config indirection ([54782e2](https://github.com/Wintersta7e/decision-spec-plan/commit/54782e212bd47d51d8913bc60db8d2533d670f2e))
* **route-state:** let a hunter clone the hunted repo out of it ([97184f3](https://github.com/Wintersta7e/decision-spec-plan/commit/97184f3eb1df81bf548b250a44d14438b50fa80f))
* **route-state:** let a hunter stash in its own clone ([25e8f20](https://github.com/Wintersta7e/decision-spec-plan/commit/25e8f20c0f6aa0165acf30036e3249bea09b1a57))
* **route-state:** never read a loop variable bash may have changed ([3936217](https://github.com/Wintersta7e/decision-spec-plan/commit/3936217ed1894d83bc2837280d86eafaed44b03b))
* **route-state:** read a computed word after a subcommand as an argument ([96a94c1](https://github.com/Wintersta7e/decision-spec-plan/commit/96a94c1ebc87ca82b1f231554c30377f2835f775))
* **route-state:** scope a hunter's taint to the shell that runs it ([262e853](https://github.com/Wintersta7e/decision-spec-plan/commit/262e853dcbd95985fb626702770def748bc254a6))
* **route-state:** take a computed word as an argument after tests only ([8399d2d](https://github.com/Wintersta7e/decision-spec-plan/commit/8399d2d473c9b10acec3f5b230c177785db708db))
* **route-state:** trust a variable only while the text cannot set it ([dc65ddf](https://github.com/Wintersta7e/decision-spec-plan/commit/dc65ddf26b99c50f7d619982592daae6675fff6c))
* **shell-cmd:** expand a for loop over its literal words ([b980d74](https://github.com/Wintersta7e/decision-spec-plan/commit/b980d741f998440df31eaeaf9e9fc1ce31abeb8a))

## [1.4.0](https://github.com/Wintersta7e/decision-spec-plan/compare/v1.3.1...v1.4.0) (2026-11-18)


### Features

* **asks:** hold a wave until each user message has an ask-list line ([82d5ba1](https://github.com/Wintersta7e/decision-spec-plan/commit/82d5ba196f7d396a07db8f0a33b0070f2ed9bb19))
* **gate,push-guard:** let one gate log count for every commit of a tree ([8e497b1](https://github.com/Wintersta7e/decision-spec-plan/commit/8e497b1186f76c34c4ff20b0faf65249dd1c4090))
* **gate:** run gates at low priority in a shared machine slot ([46376bf](https://github.com/Wintersta7e/decision-spec-plan/commit/46376bf27d265ede1605d6fc5e4f18ee7692ebc2))
* **handed:** send the lead back when a command for the user would fail ([f25e234](https://github.com/Wintersta7e/decision-spec-plan/commit/f25e234f4a1d5c0bd1a20aa523d88ebfd6ff925b))
* **lead-edits:** hold the lead's third repository file after a budget ([7f4b53f](https://github.com/Wintersta7e/decision-spec-plan/commit/7f4b53f066fd7592eadf2defe2ab2cbfe8e8564d))
* **monitor,report:** group attention by route, name plans by title ([a94a52f](https://github.com/Wintersta7e/decision-spec-plan/commit/a94a52f87492c91f09173a0e5fc0473855167438))
* **route-state:** print each due task group's Agent call with --next ([b016ec3](https://github.com/Wintersta7e/decision-spec-plan/commit/b016ec3538ec5db36a15bc94004caa62c1cb0bdd))
* **route-state:** put a Windows-drive repo's lanes on WSL's disk ([f8f0902](https://github.com/Wintersta7e/decision-spec-plan/commit/f8f0902d295c7d5adbd5d48b678e1ff21544d475))


### Bug Fixes

* **gate:** restore gate.py's executable bit ([da16e5c](https://github.com/Wintersta7e/decision-spec-plan/commit/da16e5cb5a7672fa346916fa79bea12ec4c13067))
* **report:** read a gate log's commit when more fields follow dirty= ([4c7ffb1](https://github.com/Wintersta7e/decision-spec-plan/commit/4c7ffb1e26384a873cbae74ea01b5967df6bf22e))
* **report:** read plan ids of a phase named by a word ([c4259de](https://github.com/Wintersta7e/decision-spec-plan/commit/c4259dea9c9613f8035c40ee02a2472ab01215b1))
* **report:** retire red gate logs a later green replaced ([23f249f](https://github.com/Wintersta7e/decision-spec-plan/commit/23f249f1c6f74c2a4c38c653ca2d02eba58782c2))
* **tests:** hold a lane at its Final SHA until the monitor checks it ([5dd52d3](https://github.com/Wintersta7e/decision-spec-plan/commit/5dd52d3bb2861a69e0e1fd6ae9cb1260d275496b))

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
