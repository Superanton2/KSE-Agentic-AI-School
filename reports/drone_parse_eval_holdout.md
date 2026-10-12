# Drone parser vs gold labels

150 labelled lines. `precision`/`recall` are measured on the stratified sample, which over-samples failure strata; `w_precision`/`w_recall` re-weight it to the whole stream by stratum size (the targets are checked on these). Caveat: `kind`/`count`/`oblast` are scored only on places that matched, and `oblast` counts as correct whenever the gold oblast is empty — so they mostly repeat the `place` numbers and are not independent accuracy estimates.

| channel | field | tp | fp | fn | precision | recall | w_precision | w_recall |
|---|---|---|---|---|---|---|---|---|
| kpszsu | count | 22 | 2 | 13 | 0.917 | 0.629 | 1.0 | 0.913 |
| kpszsu | kind | 22 | 2 | 13 | 0.917 | 0.629 | 1.0 | 0.913 |
| kpszsu | oblast | 22 | 2 | 13 | 0.917 | 0.629 | 1.0 | 0.913 |
| kpszsu | place | 22 | 2 | 13 | 0.917 | 0.629 | 1.0 | 0.913 |
| kudy_letyt | count | 64 | 0 | 9 | 1.0 | 0.877 | 1.0 | 0.99 |
| kudy_letyt | kind | 64 | 0 | 9 | 1.0 | 0.877 | 1.0 | 0.99 |
| kudy_letyt | oblast | 64 | 0 | 9 | 1.0 | 0.877 | 1.0 | 0.99 |
| kudy_letyt | place | 64 | 0 | 9 | 1.0 | 0.877 | 1.0 | 0.99 |
| kyiv_nebo | count | 10 | 0 | 1 | 1.0 | 0.909 | 1.0 | 0.988 |
| kyiv_nebo | kind | 10 | 0 | 1 | 1.0 | 0.909 | 1.0 | 0.988 |
| kyiv_nebo | oblast | 10 | 0 | 1 | 1.0 | 0.909 | 1.0 | 0.988 |
| kyiv_nebo | place | 10 | 0 | 1 | 1.0 | 0.909 | 1.0 | 0.988 |

## Targets

- all met

## Errors

- `kpszsu:73464:0:0` **spurious** gold=[{"place": "Київ", "oblast": "м. Київ", "kind": "ballistic", "count": 1, "role": "target", "via": null}] pred={"place_raw": "Чернігівщину", "place_norm": "Чернігівська", "oblast": "UA.02", "kind": "ballistic", "count": null, "match": "exact", "rel": "via"}
- `kpszsu:74305:0:0` **missed** gold={"place": "Дніпропетровська", "oblast": "Дніпропетровська", "kind": "kab", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:75459:0:0` **missed** gold={"place": "Тетіїв", "oblast": "Київська", "kind": "drone_jet", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:78333:0:1` **missed** gold={"place": "Компаніївка", "oblast": "Кіровоградська", "kind": "drone", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:78930:0:0` **missed** gold={"place": "Троїцьке", "oblast": "Одеська", "kind": "missile", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:78972:0:0` **missed** gold={"place": "Рокитне", "oblast": "Рівненська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:79896:0:1` **missed** gold={"place": "Нова Борова", "oblast": "Житомирська", "kind": "drone", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:80635:0:0` **spurious** gold=[{"place": "Теличка", "oblast": "м. Київ", "kind": "unknown", "count": 1, "role": "target", "via": null}] pred={"place_raw": "Києвом", "place_norm": "Київ", "oblast": "UA.12", "kind": "unknown", "count": null, "match": "lemma", "rel": "bare"}
- `kpszsu:80951:0:0` **missed** gold={"place": "Любичів", "oblast": null, "kind": "unknown", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:82537:0:0` **missed** gold={"place": "Сергіївка", "oblast": "Одеська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:83043:0:0` **missed** gold={"place": "Подільськ", "oblast": "Одеська", "kind": "drone_jet", "count": 1, "role": "via", "via": null} pred=null
- `kpszsu:83329:0:0` **missed** gold={"place": "Дніпропетровська", "oblast": "Дніпропетровська", "kind": "kab", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:83486:0:0` **missed** gold={"place": "Олександрія", "oblast": "Кіровоградська", "kind": "missile", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:83581:0:0` **missed** gold={"place": "Магдалинівка", "oblast": "Дніпропетровська", "kind": "unknown", "count": 1, "role": "target", "via": null} pred=null
- `kpszsu:83993:0:0` **missed** gold={"place": "Знам'янка", "oblast": "Кіровоградська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:114549:0:0` **missed** gold={"place": "Тростянець", "oblast": null, "kind": "missile", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:114712:0:1` **missed** gold={"place": "Лебедівка", "oblast": "Київська", "kind": "missile", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:116189:0:2` **missed** gold={"place": "Яготин", "oblast": "Київська", "kind": "missile", "count": 2, "role": "target", "via": null} pred=null
- `kudy_letyt:117755:0:24` **missed** gold={"place": "Смотрич", "oblast": "Хмельницька", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:118815:0:8` **missed** gold={"place": "Миколаївка", "oblast": "Одеська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:120832:0:9` **missed** gold={"place": "Мар'янівка", "oblast": "Житомирська", "kind": "drone", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:120955:0:9` **missed** gold={"place": "Калинопіль", "oblast": "Черкаська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:121335:0:7` **missed** gold={"place": "Миколаївка", "oblast": "Одеська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kudy_letyt:122380:0:8` **missed** gold={"place": "Помічна", "oblast": "Кіровоградська", "kind": "drone_jet", "count": 1, "role": "target", "via": null} pred=null
- `kyiv_nebo:27404:0:0` **missed** gold={"place": "Кагарлик", "oblast": "Київська", "kind": "unknown", "count": 2, "role": "target", "via": null} pred=null
