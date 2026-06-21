"""Combat filter UI catalog — menu tree maps to chats.json channel ids."""

from mnm_combat_channels import (
    BUFF_UI_SUFFIX,
    DEATH_UI_CHANNELS,
    OCR_PRESETS,
    ROLE_CHANNELS,
    UI_TARGET_SUFFIX,
    build_filter_menu,
    export_filter_ui,
)


def test_ui_target_suffix_covers_melee_labels():
    assert UI_TARGET_SUFFIX["Me"] == "Mine"
    assert UI_TARGET_SUFFIX["Mine"] == "Victim"
    assert UI_TARGET_SUFFIX["Players"] == "OtherPlayer"


def test_buff_ui_spell_tick_beneficial_me():
    menu = build_filter_menu()
    tick = menu["Spell"]["phases"]["Tick"]
    chs = tick["alignments"]["Beneficial"]["channels"]
    assert "BuffTickBenefitMine" in chs
    assert "BuffTickDetrimentVictim" in tick["alignments"]["Detrimental"]["channels"]


def test_melee_hits_channels():
    menu = build_filter_menu()
    hits = menu["Melee"]["outcomes"]["Hits"]["channels"]
    assert hits == [
        "CombatHitMine",
        "CombatHitVictim",
        "CombatHitPet",
        "CombatHitOther",
        "CombatHitOtherPlayer",
    ]


def test_death_players_maps_death_other_player():
    assert "DeathOtherPlayer" in DEATH_UI_CHANNELS["Players"]


def test_pvp_preset_channels_include_incoming_hit():
    pvp = ROLE_CHANNELS["pvp"]
    assert "CombatHitVictim" in pvp
    assert "AbilityHitDetrimentOtherPlayer" in pvp


def test_export_filter_ui_presets_match_roles():
    doc = export_filter_ui()
    for key, preset in doc["presets"].items():
        role = OCR_PRESETS[key]["role"]
        assert preset["channels"] == list(ROLE_CHANNELS[role])


def test_buff_suffix_detrimental_me_is_victim():
    assert BUFF_UI_SUFFIX[("Detrimental", "Me")] == "DetrimentVictim"
