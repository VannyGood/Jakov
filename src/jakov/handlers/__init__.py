from aiogram import Router


def all_routers() -> list[Router]:
    """In priority order: start's Cancel handlers must win over waiting-state handlers."""
    from jakov.handlers import (
        approvals,
        channels,
        emoji_admin,
        errors,
        membership,
        post_wizard,
        published,
        schedule_wizard,
        schedules,
        settings,
        start,
    )

    return [start.router, approvals.router, post_wizard.router, schedule_wizard.router,
            schedules.router, published.router, emoji_admin.router, channels.router,
            settings.router, membership.router, errors.router]
