"""One-shot Discord nickname transport with attributable journal outcomes."""

import logging
import hikari

log = logging.getLogger(__name__)


async def edit_nickname(
    rest, guild_id, target_id, *, nickname, reason, actor_id, old_nickname, source
):
    fields = (
        source,
        int(guild_id),
        int(actor_id),
        int(target_id),
        old_nickname,
        nickname,
    )
    pattern = "Nickname edit %s source=%s guild=%s actor=%s target=%s old=%r new=%r"
    log.info(pattern, "attempted", *fields)
    try:
        result = await rest.edit_member(
            guild_id, target_id, nickname=nickname, reason=reason
        )
    except (hikari.BadRequestError, hikari.ForbiddenError, hikari.NotFoundError):
        log.warning(pattern, "refused", *fields)
        raise
    except BaseException:
        # This includes cancellation: Discord may already have accepted the edit.
        log.warning(pattern, "unconfirmed", *fields)
        raise
    log.info(pattern, "confirmed", *fields)
    return result
