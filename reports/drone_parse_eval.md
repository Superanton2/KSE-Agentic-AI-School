# Drone parser vs gold labels

300 labelled lines. `precision`/`recall` are measured on the stratified sample, which over-samples failure strata; `w_precision`/`w_recall` re-weight it to the whole stream by stratum size (the targets are checked on these). Caveat: `kind`/`count`/`oblast` are scored only on places that matched, and `oblast` counts as correct whenever the gold oblast is empty — so they mostly repeat the `place` numbers and are not independent accuracy estimates.

| channel | field | tp | fp | fn | precision | recall | w_precision | w_recall |
|---|---|---|---|---|---|---|---|---|
| kpszsu | count | 63 | 0 | 11 | 1.0 | 0.851 | 1.0 | 0.953 |
| kpszsu | kind | 63 | 0 | 11 | 1.0 | 0.851 | 1.0 | 0.953 |
| kpszsu | oblast | 62 | 1 | 12 | 0.984 | 0.838 | 0.999 | 0.952 |
| kpszsu | place | 63 | 0 | 11 | 1.0 | 0.851 | 1.0 | 0.953 |
| kudy_letyt | count | 134 | 0 | 14 | 1.0 | 0.905 | 1.0 | 0.993 |
| kudy_letyt | kind | 134 | 0 | 14 | 1.0 | 0.905 | 1.0 | 0.993 |
| kudy_letyt | oblast | 134 | 0 | 14 | 1.0 | 0.905 | 1.0 | 0.993 |
| kudy_letyt | place | 134 | 0 | 14 | 1.0 | 0.905 | 1.0 | 0.993 |
| kyiv_nebo | count | 27 | 1 | 2 | 0.964 | 0.931 | 0.999 | 0.998 |
| kyiv_nebo | kind | 27 | 1 | 2 | 0.964 | 0.931 | 0.999 | 0.998 |
| kyiv_nebo | oblast | 27 | 1 | 2 | 0.964 | 0.931 | 0.999 | 0.998 |
| kyiv_nebo | place | 27 | 1 | 2 | 0.964 | 0.931 | 0.999 | 0.998 |

## Targets

- all met

## Errors

- `kpszsu:72363:0:0` **missed** gold={"place": "Затока", "oblast": "Одеська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:72560:0:1` **missed** gold={"place": "Київська", "oblast": "Київська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:74151:0:0` **missed** gold={"place": "Запоріжжя", "oblast": "Запорізька", "kind": "drone", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:75270:0:0` **missed** gold={"place": "Десна", "oblast": "Чернігівська", "kind": "drone_jet", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:76258:0:0` **missed** gold={"place": "Боромля", "oblast": "Сумська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:77760:0:0` **missed** gold={"place": "Златопіль", "oblast": "Харківська", "kind": "missile", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:79901:0:0` **missed** gold={"place": "Житомирська", "oblast": "Житомирська", "kind": "drone", "count": 1, "role": "location", "via": null} pred=null
- `kpszsu:80011:0:0` **oblast** gold={"place": "Сергіївка", "oblast": "Одеська", "kind": "drone", "count": 1, "role": "via", "via": null} pred={"place_raw": "Сергіївки", "place_norm": "Сергіївка", "oblast": "UA.08", "kind": "drone", "count": null, "match": "lemma", "rel": "via"}
- `kpszsu:80068:0:0` **missed** gold={"place": "Запорізька", "oblast": "Запорізька", "kind": "kab", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:81257:0:0` **missed** gold={"place": "Затока", "oblast": "Одеська", "kind": "kab", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:82281:0:0` **missed** gold={"place": "Іванків", "oblast": "Київська", "kind": "unknown", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:84731:0:0` **missed** gold={"place": "Козин", "oblast": "Київська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:114116:0:0` **missed** gold={"place": "Сонячне", "oblast": null, "kind": "missile", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:114116:0:1` **missed** gold={"place": "Іванівка", "oblast": null, "kind": "missile", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:115032:0:18` **missed** gold={"place": "Сергіївка", "oblast": "Одеська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:115502:0:0` **missed** gold={"place": "Лимани", "oblast": "Миколаївська", "kind": "kab", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:115895:0:1` **missed** gold={"place": "Дмитрівка", "oblast": "Дніпропетровська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:116240:0:7` **missed** gold={"place": "Білики", "oblast": "Полтавська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:117024:0:11` **missed** gold={"place": "Козирка", "oblast": "Миколаївська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:118901:0:23` **missed** gold={"place": "Смотрич", "oblast": "Хмельницька", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:118964:0:9` **missed** gold={"place": "Іршанськ", "oblast": "Житомирська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:119656:0:7` **missed** gold={"place": "Миколаївка", "oblast": "Одеська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:119934:0:3` **missed** gold={"place": "Борова", "oblast": "Київська", "kind": "drone_jet", "count": 1, "role": "target", "via": "Біла Церква"} pred=null
- `kudy_letyt:121606:0:4` **missed** gold={"place": "Вакуленчук", "oblast": "Житомирська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:121668:0:1` **missed** gold={"place": "Морозівське", "oblast": "Дніпропетровська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:122024:0:4` **missed** gold={"place": "Миколаївка", "oblast": "Одеська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kyiv_nebo:25477:0:0` **missed** gold={"place": "Бровари", "oblast": "Київська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kyiv_nebo:26658:0:0` **spurious** gold=[{"place": "Поділ", "oblast": "м. Київ", "kind": "drone", "count": 1, "role": "target", "via": null}, {"place": "Центр", "oblast": "м. Київ", "kind": "drone", "count": 1, "role": "target", "via": null}] pred={"place_raw": "Києва", "place_norm": "Київ", "oblast": "UA.12", "kind": "drone", "count": null, "match": "lemma", "rel": "target"}
- `kyiv_nebo:28120:0:0` **missed** gold={"place": "Миронівка", "oblast": "Київська", "kind": "unknown", "count": 2, "role": "via", "via": null} pred=null
