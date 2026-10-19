from aiogram import Router


def all_routers() -> list[Router]:
    """In priority order: start's Cancel handlers must win over waiting-state handlers."""
    from jakov.handlers import (
        channels,
        emoji_admin,
        errors,
        membership,
        post_wizard,
        published,
        settings,
        start,
    )

    return [start.router, post_wizard.router, published.router, emoji_admin.router,
            channels.router, settings.router, membership.router, errors.router]
