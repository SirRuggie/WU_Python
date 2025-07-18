import hikari
import lightbulb

loader = lightbulb.Loader()

@loader.listener(hikari.MessageCreateEvent)
async def on_task_command(event: hikari.MessageCreateEvent) -> None:
    if event.is_bot or event.is_webhook:
        return
    if event.author_id != 505227988229554179:
        return

    content = (event.content or "").strip().lower()

    if content == "add task":
        await event.app.rest.create_message(
            channel=event.channel_id,
            content="Ok yup, what task do you want to add?"
        )
