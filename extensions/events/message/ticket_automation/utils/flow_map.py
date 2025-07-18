# extensions/events/message/ticket_automation/utils/flow_map.py
"""
Flow map for questionnaire progression.
Defines the order of questions and their relationships.
"""

# Standard questionnaire flow
QUESTIONNAIRE_FLOW = {
    # Initial selection
    "interview_selection": "attack_strategies",

    # Main questionnaire flow
    "attack_strategies": "future_clan_expectations",
    "future_clan_expectations": "discord_basic_skills",
    "discord_basic_skills": "age_bracket",
    "discord_basic_skills_2": "age_bracket",  # Alternative discord skills flow
    "age_bracket": "timezone",
    "timezone": "leaders_checking_you_out",
    "leaders_checking_you_out": None  # End of normal flow
}

# FWA-specific flow
FWA_FLOW = {
    # FWA starts with war weight
    "war_weight": "account_collection",
    "account_collection": "interview_selection",
    "interview_selection": "fwa_explanation",  # FWA goes to education instead of questions

    # FWA education flow
    "fwa_explanation": "lazy_cwl",
    "lazy_cwl": "agreement",
    "agreement": "discord_basic_skills",  # After agreement, join normal flow

    # From here, FWA follows normal questionnaire flow
    "discord_basic_skills": "age_bracket",
    "age_bracket": "timezone",
    "timezone": "completion",  # FWA has special completion

    # FWA completion
    "completion": None  # End of FWA flow
}


def get_next_question(current_question: str, is_fwa: bool = False, fwa_step: str = None) -> str:
    """
    Get the next question in the flow.

    Args:
        current_question: Current question key
        is_fwa: Whether this is FWA flow
        fwa_step: Current FWA step if in FWA flow

    Returns:
        Next question key or None if end of flow
    """
    # For FWA flow, check FWA-specific transitions first
    if is_fwa or fwa_step:
        if current_question in FWA_FLOW:
            return FWA_FLOW[current_question]

    # Fall back to normal questionnaire flow
    return QUESTIONNAIRE_FLOW.get(current_question)


def is_final_question(question_key: str, is_fwa: bool = False) -> bool:
    """Check if this is the final question"""
    if is_fwa:
        return FWA_FLOW.get(question_key) is None
    return QUESTIONNAIRE_FLOW.get(question_key) is None


def get_flow_type(ticket_state: dict) -> tuple[bool, str]:
    """
    Determine flow type from ticket state.

    Returns:
        (is_fwa, current_fwa_step)
    """
    fwa_data = ticket_state.get("step_data", {}).get("fwa", {})
    current_fwa_step = fwa_data.get("current_fwa_step")
    is_fwa = bool(current_fwa_step) or fwa_data.get("is_fwa_ticket", False)

    return is_fwa, current_fwa_step