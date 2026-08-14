"""Frozen recognition reference for the Clash of Cards row scanner.

This module is data, not behavior.  It carries the constants and the reference
hashes of the frozen development package exactly as they were sealed, so the
production scanner in :mod:`utils.card_scan` decides identity with the same
numbers the sealed evaluator used.

Provenance and boundary, both load bearing:

* Every value here was copied from ``tools/scan_frozen_artifact.json``
  (checksum ``0b435fc4ae66675b...``), the artifact the one-time third-device
  holdout was evaluated with.  Nothing was refitted for production.
* The bank holds two coherent six-card templates per catalog row, chosen by the
  frozen ordering rule (screen position, corpus, filename) from the development
  corpora.  A template is one complete row observed in one capture; a reference
  is never assembled per card from different captures.
* The only information retained from those captures is one 128-bit grayscale
  perceptual hash per card portrait.  These values cannot reconstruct a
  screenshot, a badge, a collection, or an account.
* There is no function here that adds, replaces, or recalibrates a reference.
  Scanned player screenshots can never reach this module.  Recognition is a
  pure function of (this reference, one image).

The retired 37/6 + 313/6 candidate gate is deliberately absent.  The live gate
is ``top1 <= 48/6`` and ``top2 - top1 >= 276/6`` and lives only here.
"""

from __future__ import annotations

from types import MappingProxyType

FROZEN_SPEC_VERSION = "wu-cards scanner development freeze 2026-08-13"
FROZEN_ARTIFACT_CHECKSUM = (
    "0b435fc4ae66675beff9f94057eaed446a309a885bfac6ca1be8c322e034c0b7"
)

CATALOG_ROWS = 10
ROW_COLUMNS = 6

# Card height / card width, calibrated once from top rows, whose height the
# in-game reward bar cannot clip.  Frozen: a squeezed screenshot must fail
# rather than be re-fitted.
CARD_ASPECT = 1.2757333333333334

# The final development row gate, calibrated once against the complete frozen
# stack and never retuned.  Kept as integer sixths because that is how the
# artifact states it: a mean over six cards, in bits.
ROW_GATE_TOP1_MAX_SIXTHS = 48
ROW_GATE_GAP_MIN_SIXTHS = 276
ROW_GATE_TOP1_MAX = ROW_GATE_TOP1_MAX_SIXTHS / 6
ROW_GATE_GAP_MIN = ROW_GATE_GAP_MIN_SIXTHS / 6

# Per-slot artwork guard, judged only against same-category rivals.
SLOT_SUPPORT_MAX = 29
SLOT_GROSS = 46
SLOT_GAP_MARGIN = 10

# Independent per-slot frame category.  The nearest category must be within
# CATEGORY_TOLERANCE and lead the runner-up by CATEGORY_MARGIN, otherwise the
# answer is unknown and the row fails closed.
CATEGORY_TOLERANCE = 8.0
CATEGORY_MARGIN = 8.0
CATEGORY_MIN_LINES = 3

# Resolution-normalized band sampler.  The band is a fraction of measured card
# width, never of image width, and the sample count is fixed, so a larger
# capture cannot turn extra pixel rows into extra evidence.
BAND_TOP = 0.010
BAND_BOTTOM = 0.030
BAND_SAMPLES = 5
MIN_LINES_PER_CARD = 3
BAND_MIN_CONTRAST = 40
BAND_MIN_RUN_SHARE = 0.5
RUN_MIN_OF_PITCH = 0.45
RUN_MAX_OF_PITCH = 0.95
# Widths are integer pixel counts, so the finest spread a capture can express
# is one pixel over the card width.  Without this allowance a frozen
# proportional limit silently becomes a test of resolution.
SPREAD_QUANT_PIXELS = 1.0

FIVE_SPREAD_MAX = 0.070
ALL_SPREAD_MAX = 0.110
PITCH_MIN = 0.60
PITCH_MAX = 0.80

# Brightness-relative frame floor.  235 is the dimmest native bright end
# measured, less rounding slack.  The floor never rises above the fixed
# saturation/value predicate, so the rule is inert on any capture as bright as
# the development set and only relaxes for a measurably dim one.
NOMINAL_VALUE_P95 = 235

# What the artifact recorded about the upstream detector and the category
# centres.  A drift here means the frozen bank no longer describes this code,
# so recognition must refuse rather than answer.
EXPECTED_FRAME_MIN_SATURATION = 110
EXPECTED_FRAME_MIN_VALUE = 120
EXPECTED_CATEGORY_FRAME_HUES = MappingProxyType({
    "elixir": 211.0,
    "dark_elixir": 198.0,
    "builder_base": 145.0,
    "super_troop": 12.0,
})

# Exactly two coherent templates per catalog row, so the bank cannot
# quietly become an unequal competition between rows.
TEMPLATES_PER_ROW = 2

# The frozen catalog manifest: the exact card id and category at every one
# of the sixty slots, in order, as they stood when the bank was built.
#
# This is the load-bearing check.  A reference hash means "the artwork at
# catalog slot N", and slot N is only meaningful against this ordering.  A
# same-size reorder, a rename, or a category change would silently
# reinterpret every frozen hash against a different card, so any drift here
# must refuse rather than answer.
FROZEN_CATALOG = (
    # row 1
    ("barbarian", "elixir"),
    ("archer", "elixir"),
    ("giant", "elixir"),
    ("goblin", "elixir"),
    ("wall_breaker", "elixir"),
    ("balloon", "elixir"),
    # row 2
    ("wizard", "elixir"),
    ("healer", "elixir"),
    ("dragon", "elixir"),
    ("pekka", "elixir"),
    ("baby_dragon", "elixir"),
    ("miner", "elixir"),
    # row 3
    ("electro_dragon", "elixir"),
    ("yeti", "elixir"),
    ("dragon_rider", "elixir"),
    ("electro_titan", "elixir"),
    ("root_rider", "elixir"),
    ("thrower", "elixir"),
    # row 4
    ("meteor_golem", "elixir"),
    ("minion", "dark_elixir"),
    ("hog_rider", "dark_elixir"),
    ("valkyrie", "dark_elixir"),
    ("golem", "dark_elixir"),
    ("witch", "dark_elixir"),
    # row 5
    ("lava_hound", "dark_elixir"),
    ("bowler", "dark_elixir"),
    ("ice_golem", "dark_elixir"),
    ("headhunter", "dark_elixir"),
    ("apprentice_warden", "dark_elixir"),
    ("druid", "dark_elixir"),
    # row 6
    ("furnace", "dark_elixir"),
    ("rubble_witch", "dark_elixir"),
    ("raged_barbarian", "builder_base"),
    ("sneaky_archer", "builder_base"),
    ("boxer_giant", "builder_base"),
    ("beta_minion", "builder_base"),
    # row 7
    ("bomber", "builder_base"),
    ("bb_baby_dragon", "builder_base"),
    ("cannon_cart", "builder_base"),
    ("night_witch", "builder_base"),
    ("drop_ship", "builder_base"),
    ("power_pekka", "builder_base"),
    # row 8
    ("hog_glider", "builder_base"),
    ("super_barbarian", "super_troop"),
    ("super_archer", "super_troop"),
    ("super_giant", "super_troop"),
    ("sneaky_goblin", "super_troop"),
    ("super_wall_breaker", "super_troop"),
    # row 9
    ("rocket_balloon", "super_troop"),
    ("super_wizard", "super_troop"),
    ("super_dragon", "super_troop"),
    ("inferno_dragon", "super_troop"),
    ("super_miner", "super_troop"),
    ("super_yeti", "super_troop"),
    # row 10
    ("super_minion", "super_troop"),
    ("super_hog_rider", "super_troop"),
    ("super_valkyrie", "super_troop"),
    ("super_witch", "super_troop"),
    ("ice_hound", "super_troop"),
    ("super_bowler", "super_troop"),
)

# catalog row -> the two coherent six-card templates, each one 128-bit
# artwork hash per column, in left-to-right order.
REFERENCE_BANK = MappingProxyType({
    1: (
        (
            0xbcf38770434f484bbdbfaf60333fce33,
            0xdd83b808a1e069ff6f13032a4a6b6ee4,
            0x9edcc50ccd3e8d0ce3cc637393b7393c,
            0x8e5577267245949e30b3e373f63e1793,
            0xb425eeaca99b6c906478dbc6cbcdcfbb,
            0x447d81c659eeca5a9bd935735333b7a3,
        ),
        (
            0xbcf38770434f484bbdbfaf60333fce33,
            0xdd83b808a1e069ff6f13032a4a6b6ee4,
            0x9edcc50ccd3e8d0ce3cc637393b7393c,
            0x8e5577267245949e30b3e373f63e1793,
            0xb425eeaca99b6c906478dbc6cbcdcfbb,
            0x447d81c659eeca599bd935735333b7a3,
        ),
    ),
    2: (
        (
            0x874eba12b4d3d354f2633571cc965258,
            0xacc01d23bf871fe064d69b39325a591d,
            0x9abe45c5cc1fa2a4393c3ecbf8a0938e,
            0xb2b98e9f8ad62d023060dcdccd2b6d2f,
            0xd007d60ff9d06cd472e8c464634f9cb6,
            0x1f8f0b5cfd589051d9d8ee34dc3c3c78,
        ),
        (
            0x874eba12b4d39374f2e33571ccd65258,
            0xacc01d23bf871fe064569b39325a591d,
            0x9abe55c5cc0fa2a4393c3ecbf8a093ce,
            0xb2b98e9f8ad62c033060dcdc4d2b2daf,
            0xc007d60ff9d26cd472e8c460634f9cb6,
            0x1f8f0b5cfd389051d9d8ee34dc3c3838,
        ),
    ),
    3: (
        (
            0xf8e2027f02d8f85ea28119942d2b3bab,
            0xa9b3b87d4a213d1cd36b2e8c41656f8e,
            0xc33cc612d41cd5e7dcccedecb4c8b261,
            0xf428afd06e10e2af6928d8c48c8c83c3,
            0x3a3f698a5c3aa13c2d1d37fe4dddcf0f,
            0x8ce1d1bc7305e2c7fcbcf83f367c37f1,
        ),
        (
            0xf8a2027f02d8f95ea28199942d2b3b8a,
            0xa9b3b87d4a213d1cd36b2e8c416d6f8e,
            0xc33cc612d41cd5e7dcccedecb4c8b260,
            0xf428bfd06e10e2ab6928d8448c8c81c3,
            0x3a3f2b8e583e213c2d1d37fe4ddd4f8f,
            0x8ce1d1ac7325e2c7fcbcf83f367c37f1,
        ),
    ),
    4: (
        (
            0xc05b8fab549ba3259967e4d11e3132cb,
            0x0393cec93432e6ddd97cecf6ded96878,
            0xb28386590ed8d6fc438eada48e9639dd,
            0x1dd3b822a1bb86f4a5a33171d9ea6c5c,
            0x92e1d504a1f3e3e9fef63e3f4b5d1e76,
            0x3d8bee183fa8061d3f1f1f1e5c4c6cd9,
        ),
        (
            0xc05b8fab549ba2a599e6e4d11e3132cb,
            0x0393cee9343266ddd97cecf6ded96879,
            0xb28386590ed8d6fc439cada48eb639dd,
            0x1dd3b822a2fb86b4a5a33151d9ec6c4c,
            0x92e9d504a1f3e369fef63f3f4b5d1e76,
            0x3d8bee183fe8061c3f1f3f1e5c4cecd9,
        ),
    ),
    5: (
        (
            0xe6ac8205cfe69c4b599c9c9d96270f0f,
            0x9ce13224e72f16ba7878b881aafee678,
            0xc22d456526b26f6bccc4928761130b89,
            0xedec32ae72b284253e3d1d1f4c46b683,
            0x34ac741fe2698cf134363b7f6002669c,
            0xb84fcc0a74eb94d1d4c77970c38b375c,
        ),
        (
            0xf6ac8205cee69c4b599c9c9d96270f0f,
            0x9ce33224e72f1cb87978b891a3fae672,
            0xc2ad45e506b26e6b8cc4928565531a89,
            0xefea32aa729284353e3d1d1f4c46b689,
            0x34ac703fe2618cf334363b7fe80276ac,
            0xb84fcc0a70e9d4d3d5c77970c38b375c,
        ),
    ),
    6: (
        (
            0x412af4d171c5765de2eae8c6c3c3c0d6,
            0x6e317ae2275c8e642e5e238346c6eb09,
            0x98438f3075ae5e78ffdfeffdd3dbde7b,
            0x0f803fd01df94b1deef03c4c94dce869,
            0xac35105b345ef956dc9e8ee47643ebc8,
            0xa22cce55b57a0b17337ceed7d78b4f5b,
        ),
        (
            0x412af6d171c5761da2eae8c6c3c3c0f6,
            0x6e317ae2275c8c6c2e5e238366c6eb09,
            0x98438f2075ae5e79ffdfeffdd3dbde7b,
            0x0d803fd01df96b1deef03c4cd4dce869,
            0xae35001b165ef976dd9e8ee47643ebc8,
            0xa22cce55b55e0b17337cecd7d78b4f5b,
        ),
    ),
    7: (
        (
            0x118c5b769f0d17173c4d9cc5acdc5479,
            0xc007d60ff9d26cd472e8c460634f9cb6,
            0x99d95890a1cfe6cc808c39796b696974,
            0x278c1f84281fa7dd3d7a369ec8682c3c,
            0x10ff709dd1478d5430fcbc753355269e,
            0xfe258b0a83227f69f09981844d2e8d63,
        ),
        (
            0x118c5b769f0d17173c4cdcc5ac5c5c79,
            0xd007d60df9d26cd472e0cc60634f9cb6,
            0x99d95890a1cfe6cc808c39796b696d74,
            0x278c3784281fa7dd3d3a369ec8682c3c,
            0x10ff709dd1478f1430f8bc751355369e,
            0xfe258b0a83227de9f09981844d2e8d63,
        ),
    ),
    8: (
        (
            0xb28282190fd9dcfe63cebca48e8e3add,
            0xb56438722f0dbc36cf4b232372e6636c,
            0xc5890bdcfa01963faece798988b07060,
            0x909bad998d7c78916bf8fcf23b29edce,
            0x1300e8bd4be2cbee71d9a1636ff4b8f0,
            0x3da6d25b4856a9669d3d26144c6e2634,
        ),
        (
            0xb28282190fd9dcfe63cebca48e8e3add,
            0xb56438722f0dbc36ef4b232372e6636c,
            0xc5890bdcba05963faece798988b07060,
            0x909bad998d7c78916bf8fcfa3b29edce,
            0x1300e8bd4be2cbee71d9a1636fe6b8f0,
            0x3da4d25b4856a9e69d3d26144c6ea624,
        ),
    ),
    9: (
        (
            0x2addec7f50828b1c8f4f7f75153b3f9c,
            0x73dab0da04128ffa99b431721e2c2a2c,
            0x59b94419d88b3d5dcc0e349440f1fcb2,
            0x1d0707d366e8ec4ed2d3c69eda7ab3ba,
            0x9cc1fb5c28c817f27a7a756cea2e3468,
            0x2d683422f13e79e67636972616c7e676,
        ),
        (
            0x2addec7d50828f1c8f4f7f77153b3f9c,
            0x73dab0da04128ffa99b431721e2c2a2c,
            0x59b94439c88b3d5dcc0e349440f1fcb2,
            0x1d0707d366e8ec4ed2d3c69eda7bb1ba,
            0x9cc1fb5c28c817f27a7a756cea2e3468,
            0x2d683422f13e79e67676972616c7e676,
        ),
    ),
    10: (
        (
            0x52638ca61c2fe59ec08073238559e161,
            0xfa82c9f94ba6823698cdcc4f2d3d30a1,
            0xccd9aaa49aaa267ae6f3f19949746cad,
            0x958fe8a4b4da332a4968333acdd47c79,
            0xf655b56562b50c861367f353733e0787,
            0xa87549f6ad116c95bfbfff733beb6737,
        ),
        (
            0x52638ca61c2fe59ec08073238559e161,
            0xfa82cbf949a62236984dcc4f2d3d30a1,
            0xccd9aaa49aaa267ae6f3f19949746cad,
            0x958fe8a634da332a4968333acdd47c78,
            0xf655a56562b58c861367f353733e1f87,
            0xa87549f6ad11649dbfbfff733beb6737,
        ),
    ),
})


def catalog_manifest(catalog) -> tuple[tuple[str, str], ...]:
    """The (card id, category) manifest of a live catalog, in catalog order."""
    try:
        return tuple((str(card.id), str(card.category)) for card in catalog)
    except (AttributeError, TypeError):
        return ()


def reference_problems(
    *,
    catalog,
    frame_min_saturation: int,
    frame_min_value: int,
    category_frame_hues: dict,
) -> tuple[str, ...]:
    """Return why this reference cannot be trusted, or an empty tuple.

    The sealed evaluator verified its artifact twice over before answering a
    query.  Production cannot re-read that file, so it checks the same
    relationships against the live catalog and detector constants instead.  A
    problem here must make the scanner refuse, never guess.

    The manifest check is the authoritative one.  A reference hash only means
    anything as "the artwork at catalog slot N", so comparing the live catalog
    slot by slot - id and category, in order - is what stops a same-size
    reorder, a rename, or a recategorisation from silently reinterpreting the
    frozen hashes against different cards.  Counting sixty cards does not.
    """
    problems: list[str] = []
    if catalog_manifest(catalog) != FROZEN_CATALOG:
        problems.append("catalog_manifest_drifted")
    if sorted(REFERENCE_BANK) != list(range(1, CATALOG_ROWS + 1)):
        problems.append("reference_rows_incomplete")
    for templates in REFERENCE_BANK.values():
        if len(templates) != TEMPLATES_PER_ROW:
            problems.append("reference_template_count_changed")
            break
        if any(len(template) != ROW_COLUMNS for template in templates):
            problems.append("reference_template_not_six_cards")
            break
        if any(
            not isinstance(value, int) or not 0 <= value < (1 << 128)
            for template in templates
            for value in template
        ):
            problems.append("reference_hash_invalid")
            break
    if frame_min_saturation != EXPECTED_FRAME_MIN_SATURATION:
        problems.append("upstream_saturation_drifted")
    if frame_min_value != EXPECTED_FRAME_MIN_VALUE:
        problems.append("upstream_value_drifted")
    if dict(category_frame_hues) != dict(EXPECTED_CATEGORY_FRAME_HUES):
        problems.append("category_centres_drifted")
    if (ROW_GATE_TOP1_MAX_SIXTHS, ROW_GATE_GAP_MIN_SIXTHS) != (48, 276):
        problems.append("row_gate_drifted")
    return tuple(dict.fromkeys(problems))
