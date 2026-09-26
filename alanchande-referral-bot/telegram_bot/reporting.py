async def reply_report(message, text: str) -> None:
    """Send plain-text analytics without exceeding Telegram's message limit."""
    # 1,800 code points fit even if every character uses two UTF-16 units.
    while text:
        end = len(text) if len(text) <= 1800 else text.rfind("\n", 0, 1801)
        if end <= 0:
            end = 1800
        await message.reply_text(
            text[:end], parse_mode=None, disable_web_page_preview=True,
        )
        text = text[end:]
        if text.startswith("\n"):
            text = text[1:]
