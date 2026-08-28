# Site branch migration snapshot — 2026-08-28

This inventory freezes the latest usable site-specific PR snapshot found for the
69 site ids supplied by the maintainer. All 69 material directories resolved to
real Git objects. Sixty-six have the normalized `clone.yaml + clone/` layout.
`uber-eats`, `workable`, and `greenhouse` contain implementation files but
need a `clone.yaml` normalization step before branch activation.

PR state is preserved deliberately: 19 snapshots are merged, 33 are open
non-draft PR heads, and 17 are open draft PR heads. “Snapshot found” means that
the exact tree is recoverable; it does not claim merge, deployment, browser
fidelity acceptance, or redistribution approval.

The final persistent namespace is `sites/<id>`. The singular `site/<id>`
namespace already had 44 collisions with active or historical working branches;
the plural namespace had zero at audit time and avoids force-pushing them.

Historical material aliases are preserved:

- `confluence → materials/atlassian-confluence`
- `coursera → materials/33`
- `crumbl → materials/crumbl-cookies`
- `purelymail → materials/gmail`
- `soko-glam → materials/sokoglam`
- `uber-eats → materials/ubereats`

| Site branch id | Material id | PR state | Frozen source | Head SHA | Structure | Clone MiB | Site-specific paths |
| --- | --- | --- | --- | --- | --- | ---: | --- |
| 12go-asia | 12go-asia | merged | [reacher-z/WcodeW#14](https://github.com/reacher-z/WcodeW/pull/14) | `863e5082f429` | ready | 9 | materials/12go-asia |
| 1password-web | 1password-web | merged | [reacher-z/WcodeW#15](https://github.com/reacher-z/WcodeW/pull/15) | `504e6edebb92` | ready | 1.3 | materials/1password-web |
| ace-hardware | ace-hardware | merged | [reacher-z/WcodeW#16](https://github.com/reacher-z/WcodeW/pull/16) | `d3c5f19f87a0` | ready | 4.7 | materials/ace-hardware |
| airbnb | airbnb | merged | [reacher-z/WcodeW#17](https://github.com/reacher-z/WcodeW/pull/17) | `7674c2c493ac` | ready | 14.2 | materials/airbnb |
| airtable | airtable | merged | [reacher-z/WcodeW#18](https://github.com/reacher-z/WcodeW/pull/18) | `b1ea745ea3f1` | ready | 6.2 | materials/airtable |
| amazon-home-services | amazon-home-services | merged | [reacher-z/WcodeW#19](https://github.com/reacher-z/WcodeW/pull/19) | `4f1896647e12` | ready | 4.2 | materials/amazon-home-services |
| confluence | atlassian-confluence | open | [780078268/websitebench-pipeline#62](https://github.com/780078268/websitebench-pipeline/pull/62) | `4f50fe600303` | ready | 65.3 | materials/atlassian-confluence<br>harbor/sites/atlassian-confluence<br>harbor/instances/atlassian-confluence |
| autoslash | autoslash | open | [780078268/websitebench-pipeline#61](https://github.com/780078268/websitebench-pipeline/pull/61) | `562efaa91bd1` | ready | 13 | materials/autoslash<br>harbor/sites/autoslash<br>harbor/instances/autoslash |
| autotrader | autotrader | open | [780078268/websitebench-pipeline#60](https://github.com/780078268/websitebench-pipeline/pull/60) | `cec9af93332b` | ready | 1.9 | materials/autotrader<br>harbor/sites/autotrader<br>harbor/instances/autotrader |
| bark | bark | open | [780078268/websitebench-pipeline#59](https://github.com/780078268/websitebench-pipeline/pull/59) | `6b557a8b4835` | ready | 34.1 | materials/bark<br>harbor/sites/bark<br>harbor/instances/bark |
| bean-box | bean-box | open | [780078268/websitebench-pipeline#50](https://github.com/780078268/websitebench-pipeline/pull/50) | `ccdd492de0e5` | ready | 9.9 | materials/bean-box<br>harbor/sites/bean-box<br>harbor/instances/bean-box |
| beeradvocate | beeradvocate | open | [780078268/websitebench-pipeline#48](https://github.com/780078268/websitebench-pipeline/pull/48) | `eb17922edc5a` | ready | 1.2 | materials/beeradvocate |
| betterhelp | betterhelp | open | [780078268/websitebench-pipeline#49](https://github.com/780078268/websitebench-pipeline/pull/49) | `a8cfd948ebf0` | ready | 2.1 | materials/betterhelp |
| blinkist | blinkist | merged | [780078268/websitebench-pipeline#17](https://github.com/780078268/websitebench-pipeline/pull/17) | `e5f51348f3dc` | ready | 0.4 | materials/blinkist<br>harbor/sites/blinkist<br>harbor/instances/blinkist |
| bluemercury | bluemercury | open | [780078268/websitebench-pipeline#43](https://github.com/780078268/websitebench-pipeline/pull/43) | `dd0ceb30db57` | ready | 29.3 | materials/bluemercury<br>harbor/sites/bluemercury<br>harbor/instances/bluemercury |
| booking-com | booking-com | draft | [780078268/websitebench-pipeline#53](https://github.com/780078268/websitebench-pipeline/pull/53) | `8346bb482414` | ready | 15.1 | materials/booking-com |
| booksy | booksy | open | [780078268/websitebench-pipeline#54](https://github.com/780078268/websitebench-pipeline/pull/54) | `157de1440bac` | ready | 5.7 | materials/booksy |
| calendly | calendly | draft | [780078268/websitebench-pipeline#58](https://github.com/780078268/websitebench-pipeline/pull/58) | `67e1bfac6e24` | ready | 11.5 | materials/calendly |
| capterra | capterra | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 47.9 | materials/capterra<br>harbor/sites/capterra |
| coursera | 33 | draft | [780078268/websitebench-pipeline#97](https://github.com/780078268/websitebench-pipeline/pull/97) | `93d428f701c9` | ready | 22 | materials/33<br>harbor/sites/33<br>harbor/instances/33 |
| craigslist | craigslist | merged | [780078268/websitebench-pipeline#93](https://github.com/780078268/websitebench-pipeline/pull/93) | `27812f954027` | ready | 3.8 | materials/craigslist<br>harbor/sites/craigslist<br>harbor/instances/craigslist |
| crumbl | crumbl-cookies | open | [780078268/websitebench-pipeline#96](https://github.com/780078268/websitebench-pipeline/pull/96) | `5dc8650c0827` | ready | 56.9 | materials/crumbl-cookies |
| edx | edx | open | [780078268/websitebench-pipeline#99](https://github.com/780078268/websitebench-pipeline/pull/99) | `e27d60705755` | ready | 16.2 | materials/edx |
| eventbrite | eventbrite | open | [780078268/websitebench-pipeline#98](https://github.com/780078268/websitebench-pipeline/pull/98) | `d6b6b266ddc7` | ready | 12.9 | materials/eventbrite |
| hipcamp | hipcamp | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 15.3 | materials/hipcamp |
| insureon | insureon | draft | [780078268/websitebench-pipeline#90](https://github.com/780078268/websitebench-pipeline/pull/90) | `f5b872201d96` | ready | 11.9 | materials/insureon<br>harbor/sites/insureon<br>harbor/instances/insureon |
| insurify | insurify | draft | [780078268/websitebench-pipeline#91](https://github.com/780078268/websitebench-pipeline/pull/91) | `a50ae183f796` | ready | 16 | materials/insurify<br>harbor/sites/insurify<br>harbor/instances/insurify |
| ioby | ioby | draft | [780078268/websitebench-pipeline#92](https://github.com/780078268/websitebench-pipeline/pull/92) | `5c6be38cec88` | ready | 26.4 | materials/ioby<br>harbor/sites/ioby<br>harbor/instances/ioby |
| leetcode | leetcode | open | [780078268/websitebench-pipeline#2](https://github.com/780078268/websitebench-pipeline/pull/2) | `8967930da62a` | ready | 3.5 | materials/leetcode |
| legalnature | legalnature | open | [780078268/websitebench-pipeline#4](https://github.com/780078268/websitebench-pipeline/pull/4) | `eec4408cbf4e` | ready | 106.1 | materials/legalnature |
| lowes | lowes | open | [780078268/websitebench-pipeline#11](https://github.com/780078268/websitebench-pipeline/pull/11) | `3718f2bd2726` | ready | 3 | materials/lowes |
| mac-cosmetics | mac-cosmetics | open | [780078268/websitebench-pipeline#5](https://github.com/780078268/websitebench-pipeline/pull/5) | `6b224d8d20e5` | ready | 967.5 | materials/mac-cosmetics |
| purelymail | gmail | draft | [780078268/websitebench-pipeline#3](https://github.com/780078268/websitebench-pipeline/pull/3) | `74f27400bd58` | ready | 0.7 | materials/gmail |
| mansur-gavriel | mansur-gavriel | open | [780078268/websitebench-pipeline#24](https://github.com/780078268/websitebench-pipeline/pull/24) | `4c1c7da62a8a` | ready | 5.1 | materials/mansur-gavriel |
| masterclass | masterclass | draft | [780078268/websitebench-pipeline#112](https://github.com/780078268/websitebench-pipeline/pull/112) | `1160c080fb26` | ready | 30.2 | materials/masterclass |
| mistobox | mistobox | draft | [780078268/websitebench-pipeline#114](https://github.com/780078268/websitebench-pipeline/pull/114) | `ba90fed532af` | ready | 14.5 | materials/mistobox |
| myheritage | myheritage | open | [780078268/websitebench-pipeline#109](https://github.com/780078268/websitebench-pipeline/pull/109) | `c6fbc78b8b50` | ready | 149.4 | materials/myheritage |
| ollie | ollie | draft | [780078268/websitebench-pipeline#18](https://github.com/780078268/websitebench-pipeline/pull/18) | `d6496278084b` | ready | 17.2 | materials/ollie |
| olaplex | olaplex | open | [780078268/websitebench-pipeline#41](https://github.com/780078268/websitebench-pipeline/pull/41) | `49c9606d0549` | ready | 393.4 | materials/olaplex |
| opentable | opentable | draft | [780078268/websitebench-pipeline#111](https://github.com/780078268/websitebench-pipeline/pull/111) | `7fe0a92b908b` | ready | 5.5 | materials/opentable |
| overleaf | overleaf | open | [780078268/websitebench-pipeline#23](https://github.com/780078268/websitebench-pipeline/pull/23) | `5be998b66900` | ready | 0.4 | materials/overleaf |
| petfinder | petfinder | draft | [780078268/websitebench-pipeline#94](https://github.com/780078268/websitebench-pipeline/pull/94) | `c2389ce9b2b2` | ready | 141.2 | materials/petfinder |
| petsmart | petsmart | draft | [780078268/websitebench-pipeline#118](https://github.com/780078268/websitebench-pipeline/pull/118) | `01f91860dcdf` | ready | 11.9 | materials/petsmart<br>harbor/sites/petsmart<br>harbor/instances/petsmart |
| resy | resy | open | [780078268/websitebench-pipeline#68](https://github.com/780078268/websitebench-pipeline/pull/68) | `b43b0d7c20e4` | ready | 34.4 | materials/resy |
| rockauto | rockauto | open | [780078268/websitebench-pipeline#67](https://github.com/780078268/websitebench-pipeline/pull/67) | `c56284d736bd` | ready | 6.6 | materials/rockauto |
| roomsketcher | roomsketcher | open | [780078268/websitebench-pipeline#64](https://github.com/780078268/websitebench-pipeline/pull/64) | `fb246b3f9beb` | ready | 592.1 | materials/roomsketcher |
| rover | rover | open | [780078268/websitebench-pipeline#69](https://github.com/780078268/websitebench-pipeline/pull/69) | `d490d6bbfee1` | ready | 56 | materials/rover |
| sixt | sixt | open | [780078268/websitebench-pipeline#71](https://github.com/780078268/websitebench-pipeline/pull/71) | `28370fe25e7e` | ready | 107.4 | materials/sixt |
| soko-glam | sokoglam | open | [780078268/websitebench-pipeline#73](https://github.com/780078268/websitebench-pipeline/pull/73) | `74ecfb1bdd72` | ready | 963.5 | materials/sokoglam |
| taskrabbit | taskrabbit | draft | [780078268/websitebench-pipeline#95](https://github.com/780078268/websitebench-pipeline/pull/95) | `1a199ad7f166` | ready | 38.4 | materials/taskrabbit |
| uber-eats | ubereats | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | needs clone.yaml | 3.9 | materials/ubereats |
| tripadvisor | tripadvisor | open | [780078268/websitebench-pipeline#65](https://github.com/780078268/websitebench-pipeline/pull/65) | `f86a81cfb16d` | ready | 4.4 | materials/tripadvisor |
| trustpilot | trustpilot | open | [780078268/websitebench-pipeline#70](https://github.com/780078268/websitebench-pipeline/pull/70) | `9cd10cfe5897` | ready | 623.9 | materials/trustpilot |
| untappd | untappd | draft | [780078268/websitebench-pipeline#119](https://github.com/780078268/websitebench-pipeline/pull/119) | `4924542ddecb` | ready | 116 | materials/untappd<br>harbor/sites/untappd<br>harbor/instances/untappd |
| wix | wix | open | [780078268/websitebench-pipeline#127](https://github.com/780078268/websitebench-pipeline/pull/127) | `3abbc2beacea` | ready | 37.5 | materials/wix |
| workable | workable | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | needs clone.yaml | 13.1 | materials/workable |
| notion | notion | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 0.9 | materials/notion |
| medium | medium | open | [780078268/websitebench-pipeline#116](https://github.com/780078268/websitebench-pipeline/pull/116) | `29a4e14ee57d` | ready | 1.2 | materials/medium |
| spotify | spotify | open | [780078268/websitebench-pipeline#66](https://github.com/780078268/websitebench-pipeline/pull/66) | `9dc0919da7ff` | ready | 92.1 | materials/spotify |
| kickstarter | kickstarter | open | [780078268/websitebench-pipeline#117](https://github.com/780078268/websitebench-pipeline/pull/117) | `ec591e407a58` | ready | 14.7 | materials/kickstarter |
| greenhouse | greenhouse | draft | [780078268/websitebench-pipeline#9](https://github.com/780078268/websitebench-pipeline/pull/9) | `ec5d67308824` | needs clone.yaml | 690.3 | materials/greenhouse |
| google-scholar | google-scholar | open | [780078268/websitebench-pipeline#100](https://github.com/780078268/websitebench-pipeline/pull/100) | `51236eefb70c` | ready | 0.5 | materials/google-scholar<br>harbor/sites/google-scholar<br>harbor/instances/google-scholar |
| meetup | meetup | draft | [780078268/websitebench-pipeline#105](https://github.com/780078268/websitebench-pipeline/pull/105) | `c1449f6b9296` | ready | 34.6 | materials/meetup<br>harbor/sites/meetup<br>harbor/instances/meetup |
| change | change | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 13.6 | materials/change<br>harbor/sites/change |
| etsy | etsy | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 5.6 | materials/etsy<br>harbor/sites/etsy |
| imdb | imdb | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 12.3 | materials/imdb<br>harbor/sites/imdb |
| tripit | tripit | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 14.9 | materials/tripit |
| linkedin | linkedin | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 4.7 | materials/linkedin |
| amazon | amazon | merged | [reacher-z/WcodeW#1](https://github.com/reacher-z/WcodeW/pull/1) | `f60281516298` | ready | 69.5 | materials/amazon<br>harbor/sites/amazon<br>harbor/instances/amazon |
## Local branch-model pilot

A local pilot constructed a slim Pipeline commit and `sites/blinkist` from the
frozen Pipeline PR 17 head. A depth-1 single-branch clone of the slim branch had
no material directories; the site clone had only `materials/blinkist`,
`harbor/sites/blinkist`, and `harbor/instances/blinkist`. Both shallow clones
contained one commit. Blinkist's site suite passed 29 tests. The shared
diagnostic completed its static section with no findings; live execution was
incomplete on macOS because the candidate sandbox requires Linux.

No branch in GitHub was created or changed by this pilot.
