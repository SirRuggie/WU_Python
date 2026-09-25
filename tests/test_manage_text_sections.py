from utils import fwa_war_content, recruit_question_content
from utils.manage_text_sections import apply_modal, by_key, groups, modal_fields


def test_recruit_question_heading_and_message_share_one_edit_without_moving_credit():
    template = recruit_question_content.default_template("family_codes")
    edit_groups = groups(
        recruit_question_content.BLOCK_LABELS["family_codes"], template["sections"],
    )

    assert [(group.key, group.indexes) for group in edit_groups] == [
        ("0,1", (0, 1)), ("2", (2,)),
    ]
    paired = by_key(edit_groups, "0,1")
    assert paired is not None
    assert modal_fields(paired, template["sections"])[0][2] == template["sections"][0]

    updated = apply_modal(paired, template["sections"], {
        "title": "## A revised question", "body": "A revised request with {family_codes}",
    })
    assert updated == [
        "## A revised question", "A revised request with {family_codes}", template["sections"][2],
    ]


def test_war_heading_body_pairs_and_embedded_heading_round_trip_without_schema_changes():
    template = fwa_war_content.default_template("blacklisted")
    edit_groups = groups(fwa_war_content.BLOCK_LABELS["blacklisted"], template["sections"])

    # The result heading and clan/opponent heading remain separate; pairing two
    # headings would hide their independent structure in one field group.
    assert by_key(edit_groups, "0,1") is None
    embedded = by_key(edit_groups, "12")
    assert embedded is not None and embedded.embedded_heading is True
    fields = modal_fields(embedded, template["sections"])
    assert [field for field, _label, _value in fields] == ["title", "body"]

    updated = apply_modal(embedded, template["sections"], {
        "title": "### New help heading", "body": "Ask <@&{fwa_rep_role}> for help.",
    })
    assert len(updated) == len(template["sections"])
    assert updated[12] == "### New help heading\nAsk <@&{fwa_rep_role}> for help."
    assert updated[13] == template["sections"][13]


def test_embedded_bold_markdown_heading_is_split_using_the_native_schema():
    template = recruit_question_content.default_template("lazy_cwl_explanation")
    grouped = groups(
        recruit_question_content.BLOCK_LABELS["lazy_cwl_explanation"], template["sections"],
    )
    first_explanation = by_key(grouped, "1")
    assert first_explanation is not None and first_explanation.embedded_heading is True
    title, body = modal_fields(first_explanation, template["sections"])
    assert title[2] == "**What is Lazy CWL?**"
    assert body[2].startswith("We run CWL")


def test_old_single_field_modal_remains_valid_for_an_embedded_title_block():
    template = recruit_question_content.default_template("lazy_cwl_explanation")
    embedded = by_key(groups(
        recruit_question_content.BLOCK_LABELS["lazy_cwl_explanation"], template["sections"],
    ), "1")
    updated = apply_modal(embedded, template["sections"], {"text": "**Revised**\nExisting form value"})
    assert updated[1] == "**Revised**\nExisting form value"
