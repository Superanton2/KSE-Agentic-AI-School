from airalert.tg.locations import Location, hashtag_map, lookup, to_hashtag


def test_kyiv_city_hashtag():
    assert to_hashtag("м. Київ") == "#м_київ"
    assert lookup("#м_Київ") == Location("Kyiv City", "oblast")


def test_oblast_raion_hromada_naming_matches_dataset():
    assert lookup("#Київська_область") == Location("Kyivska oblast", "oblast")
    assert lookup("#Бучанський_район") == Location("Kyivska oblast", "raion", "Buchanskyi raion")
    loc = lookup("#м_нікополь_та_нікопольська_територіальна_громада")
    assert loc is not None and loc.level == "hromada" and loc.location == "Dnipropetrovska oblast"


def test_renamed_raion_maps_both_names_to_new_name():
    assert lookup("#Новомосковський_район") == lookup("#Самарівський_район")
    assert lookup("#Самарівський_район").raion == "Samarivskyi raion"


def test_alias_and_size():
    assert lookup("#херсон") == lookup("#м_херсон_та_херсонська_територіальна_громада")
    assert len({v.location for v in hashtag_map().values()}) == 25
