# Prose checks: business impact docs

Uncommitted. Method: `checking-prose` layer 1. Every sentence of the new or rewritten prose, extracted with tables and list items, numbered in reading order.

Sources: `docs/docs/business-impact/*.mdx`, installation Step 6 and its seed note, user walkthrough Step 5, developer walkthrough "The business impact layer".

## Subject walk: 189 sentences, 29 where the subject cannot perform the verb or the claim is wrong

| # | Page | Subject | Verb | Result |
|---|---|---|---|---|
| 1 | overview | Business impact | links | FAIL: a concept cannot link; the demo links each service |
| 2 | overview | a proposed change / a check | shows / refuses | FAIL: a change cannot show (the page shows); a check fails, Infrahub refuses the merge |
| 3 | overview | Change review | happens | ok |
| 4 | overview | A maintenance window / the router | looks / carries | ok subject; verb walk: carries |
| 5 | overview | The people | ask | ok; verb walk: answer for |
| 6 | overview | that question | gets answered | FAIL: passive hides the actor; verb walk: by hand, live in |
| 7 | overview | Infrahub | answers | FAIL: Infrahub shows the answer, it does not answer a question; verb walk: live in |
| 8 | overview | The answer / a rule | becomes / becomes | FAIL: a rule cannot become a check; you enforce it as one |
| 9 | overview | The demo | adds | FAIL (minor): the demo schema adds |
| 10 | overview | All three | are | ok |
| 11 | overview | table header | - | verb walk: lives |
| 12 | overview | table row | - | ok |
| 13 | overview | table row | - | ok |
| 14 | overview | table row | - | ok |
| 15 | overview | customer, tier, charge | are | ok |
| 16 | overview | A proposed change | can change | FAIL: you change them in a proposed change |
| 17 | overview | A service | is affected | ok (definition) |
| 18 | overview | Maintenance, provisioning, drained | count | ok |
| 19 | overview | Interface status | is not considered | ok |
| 20 | overview | The demo | builds | FAIL: the generator builds; or state the property |
| 21 | overview | A service | counts | ok |
| 22 | overview | Every figure | carries | ok subject; verb walk: carries |
| 23 | overview | list item | - | ok |
| 24 | overview | list item | - | ok |
| 25 | overview | The page | does not calculate | ok |
| 26 | overview | Money | appears | ok |
| 27 | overview | The exposure | counts | FAIL: a figure cannot count; it includes |
| 28 | overview | The demo | assumes | FAIL (minor): software does not assume; the demo data assumes |
| 29 | overview | SLAs / maintenance | exclude / carries | ok subject; verb walk: carries |
| 30 | overview | (you) | Treat | ok; verb walk: follows from |
| 31 | overview | The guard | is | ok |
| 32 | overview | It (guard) | reads / applies | ok |
| 33 | overview | it (guard) | decides | FAIL: software does not decide (org rule) |
| 34 | overview | table header | - | ok |
| 35 | overview | table row | - | ok |
| 36 | overview | The change | causes | ok |
| 37 | overview | table row | - | ok |
| 38 | overview | table row | - | ok |
| 39 | overview | A failed check | blocks | FAIL: Infrahub blocks the merge while a check has failed |
| 40 | overview | The guard / no tag | has / lets through | ok subject; verb walk: lets through |
| 41 | overview | (you) | change | ok |
| 42 | overview | The view | asks / answers | FAIL: a view cannot ask |
| 43 | overview | it (view) | counts | ok |
| 44 | overview | It (view) | counts | ok |
| 45 | overview | The view | counts | ok |
| 46 | overview | The guard | adds | ok (minor: needs) |
| 47 | overview | sources, workflows, rules | come from / are | ok |
| 48 | overview | fragment | - | ok |
| 49 | overview | The figures | are | ok |
| 50 | overview | fragment | - | ok |
| 51 | overview | That / Infrahub | belongs / holds | ok subject; verb walk: belongs in, holds |
| 52 | overview | fragment | - | ok |
| 53 | overview | The guard / Gold services | does not detect / do not survive | ok |
| 54 | overview | fragment | - | ok |
| 55 | overview | The view | counts / connects | ok |
| 56 | overview | a generator run | keeps | ok |
| 57 | overview | Opening a proposed change | did not rerun | FAIL: an action cannot rerun; Infrahub did not rerun |
| 58 | overview | (you) | run | ok |
| 59 | overview | catalog item | Take / see / watch | ok |
| 60 | overview | catalog item | Replace | ok |
| 61 | plan | You | need | ok |
| 62 | plan | anyone / you | touches / want | ok |
| 63 | plan | The demo data | contains | ok |
| 64 | plan | It (change) | sets | ok |
| 65 | plan | (you) | Install / run | ok |
| 66 | plan | The seed step | creates | ok |
| 67 | plan | change | sets | ok |
| 68 | plan | change | sets | ok |
| 69 | plan | change / service | sets / runs | ok |
| 70 | plan | The overview | explains | FAIL: a page does not explain; also 'Infrahub decides' |
| 71 | plan | (you) | Open / select | ok |
| 72 | plan | (you) | Select | ok |
| 73 | plan | The picker | opens on | ok |
| 74 | plan | The headline | reads | ok subject; verb walk: reads |
| 75 | plan | quote | - | ok |
| 76 | plan | The tiles | read | verb walk: reads |
| 77 | plan | table | - | ok |
| 78 | plan | table | - | ok |
| 79 | plan | table | - | ok |
| 80 | plan | table | - | ok |
| 81 | plan | The exposure | is | ok |
| 82 | plan | It (exposure) | counts | FAIL: a figure cannot count |
| 83 | plan | The chart | shows | ok |
| 84 | plan | Northbank | shows | FAIL: a customer cannot show; its bar shows |
| 85 | plan | Maison Verte | shows | FAIL: same as 84 |
| 86 | plan | (you) | Open | ok |
| 87 | plan | DI-1001 and DI-1002 | are | ok |
| 88 | plan | (you) | Open | ok |
| 89 | plan | Paris edge router 1 | carries | ok subject; verb walk: carries |
| 90 | plan | (you) | Select | ok |
| 91 | plan | headline / tiles | reads / read | verb walk: reads |
| 92 | plan | A switch | affects | ok |
| 93 | plan | (you) | Select | ok |
| 94 | plan | The headline | reads | verb walk: reads |
| 95 | plan | (you) | Open / sign in | ok |
| 96 | plan | (you) | Go / open | ok |
| 97 | plan | the guard | has failed | ok |
| 98 | plan | quote | - | ok |
| 99 | plan | quote | - | ok |
| 100 | plan | quote | - | ok |
| 101 | plan | The check | reads / applies | ok |
| 102 | plan | (you) | Select | ok |
| 103 | plan | Infrahub / router | refuses / stays | ok |
| 104 | plan | guard / change | has / has to be rewritten | ok |
| 105 | plan | (you) | Open | ok |
| 106 | plan | service / guard / nothing | runs / passes / stands in the way | ok subject; verb walk: stands in the way |
| 107 | plan | (you) | set | ok |
| 108 | plan | The page / the change | caches / shows | ok |
| 109 | plan | You | reviewed | ok |
| 110 | plan | The page | showed | ok |
| 111 | plan | The guard | turned | FAIL: the guard is the check; it enforced the rule |
| 112 | plan | the shared model | makes cheaper | FAIL: product-as-agent value claim |
| 113 | howto | The view | counts | ok |
| 114 | howto | The built workflows | come from | ok |
| 115 | howto | Everything else | comes from | ok; verb walk: lives |
| 116 | howto | The values | are | ok; verb walk: ship |
| 117 | howto | (you) | Edit | ok |
| 118 | howto | The page | reads | ok |
| 119 | howto | (you) | Save / refresh | ok |
| 120 | howto | Editing the file | needs | ok |
| 121 | howto | table | - | ok |
| 122 | howto | table | - | verb walk: holds |
| 123 | howto | table | - | ok |
| 124 | howto | workflow | names / lists | ok |
| 125 | howto | table | - | verb walk: make |
| 126 | howto | They | appear / add | ok |
| 127 | howto | table | - | ok |
| 128 | howto | Each source system | counts | ok |
| 129 | howto | (you) | Change | ok |
| 130 | howto | device status | comes from | ok |
| 131 | howto | this edit | changes | ok |
| 132 | howto | The rules tile | does not change | ok |
| 133 | howto | An element | matches | ok |
| 134 | howto | An element | matches | ok |
| 135 | howto | (you) | Add | ok |
| 136 | howto | Planned workflows | carry | verb walk: carry |
| 137 | howto | (you) | Use | ok |
| 138 | howto | The tile title | follows | verb walk: follows |
| 139 | howto | (you) | Add / change | ok |
| 140 | howto | (you) | Mark | ok |
| 141 | howto | The rules tile | adds up | ok |
| 142 | howto | The built workflows | are counted | ok |
| 143 | howto | Editing the file | changes | ok |
| 144 | howto | It / that | does not change / comes from | ok |
| 145 | howto | the view / the view | shows / keeps working | ok |
| 146 | install | The repository | loads | FAIL: Infrahub loads from the repository |
| 147 | install | you | create | ok |
| 148 | install | (you) | Run | ok |
| 149 | install | The walkthrough | does not need | FAIL: a walkthrough cannot need |
| 150 | install | The command | uses / takes | ok |
| 151 | install | It | runs | ok |
| 152 | install | (seed) | Waits | ok |
| 153 | install | (seed) | Creates / runs | ok |
| 154 | install | (seed) | Opens | ok |
| 155 | install | (seed) | Waits | ok |
| 156 | install | You | can run | ok |
| 157 | install | It (seed) | creates / does not change | ok |
| 158 | install | admonition title | is imported | ok |
| 159 | install | Infrahub | imports | ok |
| 160 | install | A feature / invoke seed | is not imported / waits | ok |
| 161 | userwt | the portal / Infrahub | shows / blocks | ok |
| 162 | userwt | (you) | Follow | ok |
| 163 | devwt | The business impact layer | adds / reads | FAIL: a layer cannot add or read; FACT: the seed does not read the query |
| 164 | devwt | Three parts | use | FACT FAIL: the seed task does not use the query |
| 165 | devwt | Business impact / this section | explains / covers | FAIL: page-as-agent and layout-referential |
| 166 | devwt | Two nodes and three fields | carry | verb walk: carry |
| 167 | devwt | list | - | ok |
| 168 | devwt | list | - | ok |
| 169 | devwt | Its name | must be unique | ok |
| 170 | devwt | list | - | ok |
| 171 | devwt | a proposed change | can change | FAIL: same as 16 |
| 172 | devwt | data files | loads / gives | FAIL: a file cannot load; Infrahub loads it |
| 173 | devwt | the query file | is registered | ok |
| 174 | devwt | It (query) | reads | ok |
| 175 | devwt | it (query) | answers | FAIL: a query returns data; the result shows |
| 176 | devwt | the page file | is | ok |
| 177 | devwt | The page / the figures | holds / come from | ok subject; verb walk: holds |
| 178 | devwt | list | - | ok |
| 179 | devwt | list | - | ok |
| 180 | devwt | It / the YAML file | parses / holds | ok subject; verb walk: holds |
| 181 | devwt | built_workflows.py | reads | ok |
| 182 | devwt | the check file | is registered / runs | ok |
| 183 | devwt | It (check) | runs / reuses | ok |
| 184 | devwt | It / a failed check | fails / blocks | FAIL: Infrahub blocks the merge (same as 39) |
| 185 | devwt | It | has | ok |
| 186 | devwt | the view | counts | ok |
| 187 | devwt | invoke seed | creates / runs | ok |
| 188 | devwt | It | opens | ok |
| 189 | devwt | It / the generator | pins / reuses / picks | ok |

## Verb walk: 30 non-technical verbs or expressions used in a figurative sense

| # | Verb or expression | Literal replacement |
|---|---|---|
| 4 | carries (a lab circuit) | runs through / is used for |
| 5 | answer for (it) | are responsible for |
| 6 | by hand | manually |
| 6 | live in (a separate CRM) | are stored in |
| 7 | live in (the same graph) | are stored in |
| 8 | becomes (a check) | is enforced as |
| 11 | lives (Where it lives) | Where it is stored |
| 22 | carries (a label) | has |
| 29 | carries (no SLA credit) | leads to no SLA credit |
| 30 | follows from | depends on |
| 40 | lets (the change) through | allows the change to merge |
| 51 | belongs in | is kept in |
| 51 | holds (the relationships) | stores |
| 74 | reads | shows |
| 76 | read | show |
| 91 | reads / read | shows / show |
| 94 | reads | shows |
| 89 | carries (the marker) | has |
| 106 | stands in the way of | blocks |
| 111 | turned (into) | enforced |
| 112 | makes cheaper | reduces what you build |
| 115 | lives (today) | is stored |
| 116 | ship with | are included in |
| 122 | holds (it today) | stores |
| 125 | make (them) | contain them |
| 136 | carry | show |
| 138 | follows (the number) | shows |
| 166 | carry | store |
| 177 | holds | contains |
| 180 | holds | contains |

## Re-walk of rewritten prose (2026-10-05, after the fixes)

The fixes above and the old-prose rewrites on the edited pages are new prose, so they were walked again: 133 added or changed sentences in `git diff 054a378 -- docs/docs` (table rows and list items included), across the three business impact pages, installation, both walkthroughs and the home page. This re-walk records only the failures, not a row per sentence. 5 failed and were rewritten:

| Sentence | Problem | Rewritten |
|---|---|---|
| "the stock Infrahub image does not install `service_catalog`" | an image cannot install | "`service_catalog` is not installed in the stock Infrahub image" |
| "The demo also links each service to its customer" (home) | a demo cannot link | "In the demo, each service is also linked to its customer" |
| "A generator turns a service request into the infrastructure objects" | figurative "turns into" | "A generator creates the infrastructure objects that implement a service request" |
| "The business impact layer stores business context" | a layer cannot store | "In the business impact layer, business context is stored" |
| "its configuration follows the same rules" | figurative "follows" | "its configuration uses the same rules" |

Verb walk on the rewritten prose: the 30 figurative verbs above are replaced; no new figurative verb was found beyond the two in the table.
